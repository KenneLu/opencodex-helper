#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
opencodex 助手（opencodex-helper）
多目标 SSH 反向隧道管理：把多台 VM 的 127.0.0.1:10100 转发到本机 opencodex。
认证：优先 SSH 密钥；无令牌时用内置 plink + 密码（弹窗输入，仅内存缓存）。
启动时自动扫描各目标的令牌状态，菜单中用钥匙符号显示。
内置 opencodex 服务控制（启停/重启/健康/安全状态），替代官方托盘。
"""
import functools
import json
import logging
import os
import shlex
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

import psutil
import pystray
from PIL import Image, ImageDraw

import log_kit
import paths
import tray_kit
import update_helper
from paths import CONFIG_PATH, LOG_DIR, UPDATE_DIR, USER_DATA_DIR

APP_DIR = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
# 用户数据区/配置/日志/更新暂存：唯一出处 = T2 paths（数据区住 LOCALAPPDATA，
# 1.0 及以前的 exe 旁旧配置由播种自动迁入）。
SSH_KEYGEN = r"C:\Windows\System32\OpenSSH\ssh-keygen.exe"


def _resource_path(name):
    """PyInstaller onedir 打包后数据文件在 _internal（sys._MEIPASS）；优先内置，其次 exe 同目录。"""
    if getattr(sys, "frozen", False):
        meipass = Path(getattr(sys, "_MEIPASS", APP_DIR))
        p = meipass / name
        if p.exists():
            return p
    return APP_DIR / name


PLINK_PATH = _resource_path("bin/plink.exe")

APP_NAME = "opencodex 助手"
VERSION = "1.2.0"

DEFAULT_CONFIG = {
    "targets": [],
    "local_port": 10100,
    "probe_interval_sec": 600,
    "ssh_connect_timeout_sec": 6,
    "probe_timeout_sec": 4,
    "dashboard_url": "http://127.0.0.1:10100",
    "ocx_cmd": "",
    "opencodex_home": "",
}

LOG_DIR.mkdir(parents=True, exist_ok=True)
_logger = log_kit.get_logger(LOG_DIR)   # T12：滚动 1MB×3（house 标准 D13）


def _log(msg):
    _logger.info(msg)

# ---------------- 配置 ----------------
def load_config():
    paths.seed_config()   # T2：exe 旁旧配置一次性迁入用户数据区
    cfg = {}
    if CONFIG_PATH.exists():
        try:
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            _log(f"config load failed: {e}")
    merged = {**DEFAULT_CONFIG, **cfg}
    # 旧版迁移：ssh_host 单目标 -> targets
    if "ssh_host" in cfg and not cfg.get("targets"):
        rp = cfg.get("remote_port", merged.get("local_port", 10100))
        merged["targets"] = [{
            "name": cfg["ssh_host"], "user": "", "host": cfg["ssh_host"],
            "port": 22, "key": "", "remote_port": rp, "enabled": True,
        }]
    merged.pop("remote_port", None)
    if not merged.get("targets"):
        merged["targets"] = [{
            "name": "Ubuntu24.04", "user": "xzy_admin", "host": "192.168.190.128",
            "port": 22, "key": "", "remote_port": merged.get("local_port", 10100), "enabled": True,
        }]
    for t in merged["targets"]:
        t.setdefault("name", t.get("host", "?"))
        t.setdefault("user", "")
        t.setdefault("host", "")
        t.setdefault("port", 22)
        t.setdefault("key", "")
        t.setdefault("remote_port", merged.get("local_port", 10100))
        t.setdefault("enabled", True)
    return merged

CFG = load_config()

def save_config():
    try:
        data = {
            "targets": CFG["targets"],
            "local_port": CFG.get("local_port", 10100),
            "probe_interval_sec": CFG.get("probe_interval_sec", 600),
            "ssh_connect_timeout_sec": CFG.get("ssh_connect_timeout_sec", 6),
            "probe_timeout_sec": CFG.get("probe_timeout_sec", 4),
            "dashboard_url": CFG.get("dashboard_url", "http://127.0.0.1:10100"),
            "ocx_cmd": CFG.get("ocx_cmd", ""),
            "opencodex_home": CFG.get("opencodex_home", ""),
        }
        CONFIG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        _log(f"save config failed: {e}")

# ---------------- 工具 ----------------
HOME_DIR = str(Path.home())
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

def run_hidden(cmd, **kwargs):
    kwargs.setdefault("creationflags", CREATE_NO_WINDOW)
    kwargs.setdefault("cwd", HOME_DIR)
    return subprocess.run(cmd, **kwargs)

def target_key(t):
    return f"{t.get('user','')}@{t.get('host','')}:{t.get('port',22)}"

def conn_str(t):
    return f"{t['user']}@{t['host']}" if t.get("user") else t["host"]

def ssh_args(t, extra=None):
    a = ["ssh", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={CFG['ssh_connect_timeout_sec']}",
         "-o", "StrictHostKeyChecking=accept-new", "-p", str(t.get("port", 22))]
    if t.get("key"):
        a += ["-i", str(Path(t["key"]).expanduser())]
    if extra:
        a += extra
    return a

def plink_args(t, pw, remote_cmd=None):
    a = [str(PLINK_PATH), "-batch", "-pw", pw, "-P", str(t.get("port", 22))]
    if remote_cmd is not None:
        a += [conn_str(t), remote_cmd]
    else:
        a += ["-R", f"{t.get('remote_port',10100)}:127.0.0.1:{CFG['local_port']}", conn_str(t)]
    return a

# ---------------- 状态 ----------------
_state = {}          # target_key -> bool（隧道连接状态）
_token_status = {}   # target_key -> True/False/None
_tunnel_procs = {}   # target_key -> Popen
_pw_cache = {}       # target_key -> 密码（仅内存）
_lock = threading.Lock()

def enabled_targets():
    return [t for t in CFG["targets"] if t.get("enabled", True)]

def global_connected_count():
    n = 0
    for t in CFG["targets"]:
        if t.get("enabled", True) and _state.get(target_key(t)):
            n += 1
    return n

def enabled_count():
    return len(enabled_targets())

# ---------------- 探测 / 令牌扫描 ----------------
def probe_target(t):
    key = target_key(t)
    remote = f"curl -sf -m {CFG['probe_timeout_sec']} http://127.0.0.1:{t.get('remote_port',10100)}/healthz"
    tok = _token_status.get(key)
    if tok is not False:
        try:
            r = run_hidden(ssh_args(t, [conn_str(t), remote]), capture_output=True, text=True,
                           timeout=CFG["ssh_connect_timeout_sec"] + CFG["probe_timeout_sec"] + 8)
            if r.returncode == 0 and '"service":"opencodex"' in r.stdout:
                return True
        except Exception:
            pass
    pw = _pw_cache.get(key)
    if pw and PLINK_PATH.exists():
        try:
            r = run_hidden(plink_args(t, pw, remote), capture_output=True, text=True,
                           timeout=CFG["ssh_connect_timeout_sec"] + CFG["probe_timeout_sec"] + 8)
            if r.returncode == 0 and '"service":"opencodex"' in r.stdout:
                return True
        except Exception:
            pass
    return False

def scan_target_token(t):
    cmd = ssh_args(t, ["-o", "PreferredAuthentications=publickey", "-o", "PasswordAuthentication=no",
                       conn_str(t), "true"])
    try:
        r = run_hidden(cmd, capture_output=True, text=True, timeout=12)
        if r.returncode == 0:
            return True
        err = (r.stderr + r.stdout).lower()
        if ("permission denied" in err or "publickey" in err or
                "authentication failed" in err or "no more authentication" in err):
            return False
        return None
    except Exception:
        return None

def scan_all_tokens():
    targets = CFG["targets"]
    if not targets:
        return
    with ThreadPoolExecutor(max_workers=min(4, len(targets))) as ex:
        futs = {ex.submit(scan_target_token, t): t for t in targets}
        for fut, t in futs.items():
            _token_status[target_key(t)] = fut.result()
    _log("token scan: " + json.dumps({k: v for k, v in _token_status.items()}, ensure_ascii=False))

def initial_probe_all():
    for t in enabled_targets():
        _state[target_key(t)] = probe_target(t)

# ---------------- 隧道启停 ----------------
def kill_target_procs(t):
    key = target_key(t)
    proc = _tunnel_procs.pop(key, None)
    if proc:
        try:
            proc.terminate()
        except Exception:
            pass
    target = f"{t.get('remote_port',10100)}:127.0.0.1:{CFG['local_port']}"
    cs = conn_str(t)
    for p in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            cmd = p.info.get("cmdline") or []
            joined = " ".join(cmd)
            name = (p.info.get("name") or "").lower()
            if target in joined and cs in joined and (name.startswith("ssh") or "plink" in name):
                p.terminate()
        except Exception:
            pass

def ensure_plink_hostkey(t, pw):
    if not PLINK_PATH.exists():
        return
    cmd = f'echo y | "{PLINK_PATH}" -pw {shlex.quote(pw)} -P {t.get("port",22)} {shlex.quote(conn_str(t))} "true"'
    run_hidden(cmd, shell=True, capture_output=True, text=True, timeout=20)

def start_target(t):
    key = target_key(t)
    if probe_target(t):
        _state[key] = True
        _log(f"start target {t['name']}: already connected")
        return False, f"{t['name']} 隧道已连接，未重复启动"
    kill_target_procs(t)
    tok = _token_status.get(key)
    pw = _pw_cache.get(key)
    if tok is False and not pw:
        pw = ask_password(t)
        if not pw:
            _state[key] = False
            _log(f"start target {t['name']}: password required, cancelled")
            return False, f"{t['name']}: 需要密码（或先生成 SSH 令牌）"
        _pw_cache[key] = pw
    if tok is False or (pw and tok is not True):
        ensure_plink_hostkey(t, pw)
        cmd = plink_args(t, pw)
    else:
        cmd = ssh_args(t, ["-N", "-R", f"{t.get('remote_port',10100)}:127.0.0.1:{CFG['local_port']}", conn_str(t)])
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                creationflags=CREATE_NO_WINDOW, cwd=HOME_DIR)
    except Exception as e:
        _state[key] = False
        _log(f"start target {t['name']} failed: {e}")
        return False, f"{t['name']} 启动失败: {e}"
    _tunnel_procs[key] = proc
    time.sleep(2.5)
    ok = probe_target(t)
    _state[key] = ok
    _log(f"start target {t['name']}: ok={ok}")
    return ok, f"{t['name']} 隧道已连接" if ok else f"{t['name']} 隧道未就绪"

def stop_target(t):
    key = target_key(t)
    if not probe_target(t):
        kill_target_procs(t)
        _state[key] = False
        _log(f"stop target {t['name']}: not running")
        return False, f"{t['name']} 隧道未运行，未重复停止"
    kill_target_procs(t)
    time.sleep(1)
    ok = probe_target(t)
    _state[key] = ok
    _log(f"stop target {t['name']}: stopped={not ok}")
    return not ok, f"{t['name']} 隧道已停止" if not ok else f"{t['name']} 停止失败"

# ---------------- Tk 对话框 ----------------
def _tk_root(title):
    root = tk.Tk()
    root.title(title)
    root.attributes("-topmost", True)
    return root

def ask_password(t):
    try:
        root = _tk_root(f"opencodex 助手 - 密码")
        root.geometry("360x140")
        ttk.Label(root, text=f"目标: {t['name']}  {conn_str(t)}").pack(padx=12, pady=(14, 4), anchor="w")
        ttk.Label(root, text="SSH 密码（仅本次使用，不保存）:").pack(padx=12, pady=4, anchor="w")
        var = tk.StringVar()
        e = ttk.Entry(root, textvariable=var, show="*", width=40)
        e.pack(padx=12, pady=4)
        result = {}
        def on_ok():
            result["pw"] = var.get()
            root.destroy()
        def on_cancel():
            root.destroy()
        frm = ttk.Frame(root)
        frm.pack(pady=10)
        ttk.Button(frm, text="确定", command=on_ok).pack(side="left", padx=8)
        ttk.Button(frm, text="取消", command=on_cancel).pack(side="left", padx=8)
        root.bind("<Return>", lambda _e: on_ok())
        e.focus_set()
        root.mainloop()
        return result.get("pw")
    except Exception as e:
        _log(f"ask_password failed: {e}")
        return None

def dialog_edit_target(t=None):
    """t=None 表示添加；返回 dict 或 None（取消）"""
    is_edit = t is not None
    root = _tk_root("编辑目标" if is_edit else "添加目标")
    root.geometry("420x330")
    fields = [
        ("名称", "name", "Ubuntu24.04"),
        ("用户名", "user", "xzy_admin"),
        ("主机 / IP", "host", "192.168.190.128"),
        ("SSH 端口", "port", "22"),
        ("远端端口", "remote_port", str(CFG.get("local_port", 10100))),
    ]
    init = {k: str(t.get(k, d)) if k not in ("name", "user", "host") else str(t.get(k, d))
            for k, d, _ in fields} if is_edit else {k: d for k, d, _ in fields}
    init["port"] = str(t.get("port", 22)) if is_edit else "22"
    init["remote_port"] = str(t.get("remote_port", CFG.get("local_port", 10100))) if is_edit else str(CFG.get("local_port", 10100))
    vars_ = {}
    frm = ttk.Frame(root, padding=12)
    frm.pack(fill="both", expand=True)
    for i, (label, key, _d) in enumerate(fields):
        ttk.Label(frm, text=label).grid(row=i, column=0, sticky="w", pady=3)
        vars_[key] = tk.StringVar(value=init.get(key, ""))
        ttk.Entry(frm, textvariable=vars_[key], width=34).grid(row=i, column=1, pady=3)
    ttk.Label(frm, text="密钥文件（留空=默认 ~/.ssh）").grid(row=len(fields), column=0, sticky="w", pady=3)
    vars_["key"] = tk.StringVar(value=str(t.get("key", "")) if is_edit else "")
    key_row = len(fields)
    ttk.Entry(frm, textvariable=vars_["key"], width=26).grid(row=key_row, column=1, sticky="w", pady=3)
    def browse_key():
        p = filedialog.askopenfilename(title="选择私钥文件", initialdir=str(Path.home() / ".ssh"))
        if p:
            vars_["key"].set(p)
    ttk.Button(frm, text="浏览…", command=browse_key).grid(row=key_row, column=1, sticky="e", pady=3)
    # 本机已扫描到的密钥提示
    keys = scan_local_keys()
    if keys:
        ttk.Label(frm, text="本机密钥: " + " / ".join(Path(k).name for k in keys),
                  foreground="#666").grid(row=key_row + 1, column=0, columnspan=2, sticky="w", pady=2)
    vars_["enabled"] = tk.BooleanVar(value=t.get("enabled", True) if is_edit else True)
    ttk.Checkbutton(frm, text="启用（参与隧道与状态）", variable=vars_["enabled"]).grid(
        row=key_row + 2, column=0, columnspan=2, sticky="w", pady=4)
    result = {}
    def on_ok():
        try:
            result["name"] = vars_["name"].get().strip() or "?"
            result["user"] = vars_["user"].get().strip()
            result["host"] = vars_["host"].get().strip()
            result["port"] = int(vars_["port"].get().strip() or 22)
            result["remote_port"] = int(vars_["remote_port"].get().strip() or CFG.get("local_port", 10100))
            result["key"] = vars_["key"].get().strip()
            result["enabled"] = vars_["enabled"].get()
            if not result["host"]:
                messagebox.showwarning("提示", "主机 / IP 不能为空", parent=root)
                return
            root.destroy()
        except Exception:
            messagebox.showerror("错误", "端口必须是数字", parent=root)
    def on_cancel():
        root.destroy()
    btns = ttk.Frame(root)
    btns.pack(pady=8)
    ttk.Button(btns, text="确定", command=on_ok).pack(side="left", padx=8)
    ttk.Button(btns, text="取消", command=on_cancel).pack(side="left", padx=8)
    root.mainloop()
    return result or None

def pick_target(title):
    targets = CFG["targets"]
    if not targets:
        return None
    if len(targets) == 1:
        return targets[0]
    root = _tk_root(title)
    root.geometry("360x260")
    lb = tk.Listbox(root)
    lb.pack(fill="both", expand=True, padx=10, pady=10)
    for i, t in enumerate(targets):
        tok = _token_status.get(target_key(t))
        tok_s = "🔑" if tok is True else ("🚫" if tok is False else "?")
        lb.insert(tk.END, f"{t['name']}  {t['host']}  {tok_s}")
    sel = {}
    def on_ok():
        i = lb.curselection()
        if i:
            sel["t"] = targets[i[0]]
        root.destroy()
    def on_cancel():
        root.destroy()
    btns = ttk.Frame(root)
    btns.pack(pady=8)
    ttk.Button(btns, text="确定", command=on_ok).pack(side="left", padx=8)
    ttk.Button(btns, text="取消", command=on_cancel).pack(side="left", padx=8)
    root.mainloop()
    return sel.get("t")

def scan_local_keys():
    keys = []
    ssh_dir = Path.home() / ".ssh"
    if ssh_dir.exists():
        for name in ("id_ed25519", "id_rsa", "id_ecdsa", "id_ed25519_opencodex_helper"):
            if (ssh_dir / name).exists():
                keys.append(str(ssh_dir / name))
    return keys

# ---------------- 生成 / 部署令牌 ----------------
def generate_token_for_target(t):
    key = target_key(t)
    root = _tk_root("生成 SSH 令牌")
    ok = messagebox.askyesno(
        "生成 SSH 令牌",
        f"将为本机生成 ed25519 密钥并部署公钥到目标 {t['name']} ({conn_str(t)})。\n\n"
        "说明：\n"
        "  1. 私钥生成在 ~/.ssh/（无口令，请妥善保管）\n"
        "  2. 公钥自动追加到目标的 ~/.ssh/authorized_keys\n"
        "  3. 部署需要目标的 SSH 密码，仅本次使用、不保存\n\n"
        "是否继续？",
        parent=root,
    )
    root.destroy()
    if not ok:
        return False, "已取消"
    key_path = Path.home() / ".ssh" / "id_ed25519"
    if key_path.exists():
        key_path = Path.home() / ".ssh" / "id_ed25519_opencodex_helper"
    key_path.parent.mkdir(parents=True, exist_ok=True)
    r = run_hidden([SSH_KEYGEN, "-t", "ed25519", "-f", str(key_path), "-N", "",
                    "-C", "opencodex-helper"],
                   capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        return False, f"密钥生成失败: {r.stderr.strip()[:200]}"
    pub = key_path.with_suffix(".pub").read_text(encoding="utf-8").strip()
    pw = ask_password(t)
    if not pw:
        return False, "已取消部署（密钥已生成，可稍后手动部署）"
    _pw_cache[key] = pw
    ensure_plink_hostkey(t, pw)
    remote = ("mkdir -p ~/.ssh && chmod 700 ~/.ssh && touch ~/.ssh/authorized_keys && "
              "grep -qF -- {q} ~/.ssh/authorized_keys || echo {q} >> ~/.ssh/authorized_keys && "
              "chmod 600 ~/.ssh/authorized_keys").format(q=shlex.quote(pub))
    rd = run_hidden(plink_args(t, pw, remote), capture_output=True, text=True, timeout=25)
    if rd.returncode != 0:
        _log(f"deploy pubkey failed: {rd.stderr}")
        return False, f"公钥部署失败: {rd.stderr.strip()[:200]}"
    t["key"] = str(key_path)
    save_config()
    _token_status[key] = True
    return True, f"令牌已生成并部署到 {t['name']}"

# ---------------- 菜单动作 ----------------
def make_toggle_action(t):
    def action(icon, item):
        key = target_key(t)
        t["enabled"] = not t.get("enabled", True)
        save_config()
        _log(f"toggle target {t['name']}: enabled={t['enabled']}")
        if t["enabled"]:
            threading.Thread(target=lambda: do_action(icon, lambda: start_target(t)), daemon=True).start()
        else:
            threading.Thread(target=lambda: do_action(icon, lambda: stop_target(t)), daemon=True).start()
        refresh_icon(icon)
    return action

def target_line(t):
    key = target_key(t)
    tok = _token_status.get(key)
    tok_sym = "🔑" if tok is True else ("🚫" if tok is False else "?")
    ok = _state.get(key, False)
    state_sym = "●" if ok else "○"
    return f"{'☑' if t.get('enabled', True) else '☐'} {t['name']}  {t['host']}  {state_sym} {tok_sym}"

def on_add_target(icon, item):
    def _run():
        d = dialog_edit_target()
        if d:
            CFG["targets"].append(d)
            save_config()
            _log(f"add target: {d['name']} {d['host']}")
            threading.Thread(target=lambda: scan_and_refresh(icon, [d]), daemon=True).start()
            try:
                icon.notify(f"已添加目标 {d['name']}", APP_NAME)
            except Exception:
                pass
    threading.Thread(target=_run, daemon=True).start()

def on_edit_target(icon, item):
    def _run():
        t = pick_target("选择要编辑的目标")
        if not t:
            return
        d = dialog_edit_target(t)
        if d:
            t.update(d)
            save_config()
            _log(f"edit target: {t['name']} {t['host']}")
            refresh_icon(icon)
    threading.Thread(target=_run, daemon=True).start()

def on_delete_target(icon, item):
    def _run():
        t = pick_target("选择要删除的目标")
        if not t:
            return
        root = _tk_root("删除目标")
        ok = messagebox.askyesno("删除目标", f"确定删除目标 {t['name']}（{t['host']}）？", parent=root)
        root.destroy()
        if not ok:
            return
        kill_target_procs(t)
        CFG["targets"] = [x for x in CFG["targets"] if x is not t]
        save_config()
        _log(f"delete target: {t['name']}")
        refresh_icon(icon)
    threading.Thread(target=_run, daemon=True).start()

def on_generate_token(icon, item):
    def _run():
        targets = CFG["targets"]
        # 优先无令牌且启用的目标
        cand = [t for t in targets if _token_status.get(target_key(t)) is False]
        pick = cand[0] if len(cand) == 1 else pick_target("选择要生成令牌的目标")
        if not pick:
            return
        ok, msg = generate_token_for_target(pick)
        _log(f"generate token {pick['name']}: ok={ok} msg={msg}")
        try:
            icon.notify(msg, APP_NAME)
        except Exception:
            pass
        refresh_icon(icon)
    threading.Thread(target=_run, daemon=True).start()

def on_rescan_tokens(icon, item):
    def _run():
        scan_all_tokens()
        refresh_icon(icon)
        try:
            icon.notify("令牌扫描完成", APP_NAME)
        except Exception:
            pass
    threading.Thread(target=_run, daemon=True).start()

def scan_and_refresh(icon, targets):
    for t in targets:
        _token_status[target_key(t)] = scan_target_token(t)
    refresh_icon(icon)

def on_start_all(icon, item):
    def _run():
        for t in enabled_targets():
            if not _state.get(target_key(t)):
                do_action(icon, lambda: start_target(t))
        refresh_icon(icon)
    threading.Thread(target=_run, daemon=True).start()

def on_stop_all(icon, item):
    def _run():
        for t in enabled_targets():
            if _state.get(target_key(t)):
                do_action(icon, lambda: stop_target(t))
        refresh_icon(icon)
    threading.Thread(target=_run, daemon=True).start()

def on_toggle_autostart(icon, item):
    set_autostart(not autostart_enabled())
    _log(f"autostart -> {autostart_enabled()}")
    refresh_icon(icon)

def on_open_dashboard(icon, item):
    _log(f"open dashboard: {CFG['dashboard_url']}")
    webbrowser.open(CFG["dashboard_url"])

def on_open_log(icon, item):
    os.startfile(str(LOG_DIR))  # noqa

def on_quit(icon, item):
    _log("quit")
    for t in CFG["targets"]:
        kill_target_procs(t)
    icon.stop()
    if update_helper.PENDING_CMD:
        # 本进程退出后由脚本接管：等待 → robocopy 铺新版 → 重启新 exe → 自删
        os.system('start "" /min "%s"' % update_helper.PENDING_CMD)

# ---------------- 托盘 / 菜单 ----------------
def refresh_icon(icon):
    try:
        with _lock:
            connected = global_connected_count() > 0
        icon.icon = make_icon_image(connected)
        icon.update_menu()
    except Exception:
        pass

def notify_status_change(icon, name, ok):
    msg = f"{name} 隧道已连接" if ok else f"{name} 隧道已断开"
    try:
        icon.notify(msg, APP_NAME)
    except Exception:
        pass

def monitor_loop(icon):
    first = True
    while True:
        time.sleep(CFG.get("probe_interval_sec", 600))
        for t in enabled_targets():
            key = target_key(t)
            ok = probe_target(t)
            with _lock:
                prev = _state.get(key, False)
                _state[key] = ok
            if not first and ok != prev:
                notify_status_change(icon, t["name"], ok)
        first = False
        refresh_icon(icon)

def save_config_set_probe(icon, item, seconds):
    CFG["probe_interval_sec"] = seconds
    save_config()
    try:
        icon.update_menu()
        icon.notify(f"状态刷新间隔已设为 {seconds} 秒", APP_NAME)
    except Exception:
        pass

PROBE_CHOICES = [(20, "20 秒"), (60, "1 分钟"), (300, "5 分钟"), (600, "10 分钟"),
                 (1800, "30 分钟"), (3600, "1 小时")]

def build_probe_menu():
    return pystray.Menu(*[
        pystray.MenuItem(label, functools.partial(save_config_set_probe, seconds=sec),
                         checked=lambda item, s=sec: CFG.get("probe_interval_sec", 600) == s)
        for sec, label in PROBE_CHOICES
    ])

def build_targets_menu():
    items = []
    for t in CFG["targets"]:
        items.append(pystray.MenuItem(
            lambda item, tt=t: target_line(tt),
            make_toggle_action(t),
            checked=lambda item, tt=t: tt.get("enabled", True),
        ))
    items.append(pystray.Menu.SEPARATOR)
    items.append(pystray.MenuItem("＋ 添加目标…", on_add_target))
    items.append(pystray.MenuItem("✎ 编辑目标…", on_edit_target))
    items.append(pystray.MenuItem("－ 删除目标…", on_delete_target))
    items.append(pystray.MenuItem("🔑 生成 SSH 令牌…", on_generate_token))
    items.append(pystray.MenuItem("↻ 重新扫描令牌", on_rescan_tokens))
    return pystray.Menu(*items)

def status_line():
    n = global_connected_count()
    e = enabled_count()
    return f"隧道状态: 已连接 ({n}/{e})" if n else "隧道状态: 未连接"

def check_update_menu(_icon=None, _item=None):
    def worker():
        result = update_helper.check_update(VERSION, force=True)
        if result.get("newer"):
            notify_status_change(_icon, f"发现新版本 {result['latest']}（当前 {VERSION}），菜单「下载并更新」可用", True)
        elif result.get("error"):
            notify_status_change(_icon, f"检查更新失败：{result['error']}", False)
        else:
            notify_status_change(_icon, f"已是最新版本 {VERSION}", True)
        try:
            _icon.update_menu()
        except Exception:
            pass
    threading.Thread(target=worker, daemon=True).start()


def download_update_menu(_icon=None, _item=None):
    latest = update_helper.UPDATE_READY
    if not latest or not getattr(sys, "frozen", False):
        return

    def worker():
        try:
            update_helper.download_and_prepare(latest, APP_DIR, UPDATE_DIR, log=_log)
            _icon.notify("更新已就绪，退出托盘后将自动完成升级并重启", APP_NAME)
        except Exception as e:
            _log(f"update download failed: {e}")
            _icon.notify(f"下载更新失败：{e}", APP_NAME)
        try:
            _icon.update_menu()
        except Exception:
            pass
    threading.Thread(target=worker, daemon=True).start()


def build_menu():
    """house 标准八段式（执行文档 D14）：信息 → 更新 → 默认入口 → 服务控制 → 业务 → 打开 → 偏好 → 退出。"""
    return pystray.Menu(
        # ① 信息区（只读；此前 ocx 状态行错位在菜单中部，本次归位到顶上）
        pystray.MenuItem(lambda item: f"{APP_NAME} v{VERSION}", None, enabled=False),
        pystray.MenuItem(lambda item: status_line(), None, enabled=False),
        pystray.MenuItem(lambda item: ocx_status_line(), None, enabled=False),
        pystray.MenuItem(lambda item: ocx_safety_line(), None, enabled=False),
        pystray.Menu.SEPARATOR,
        # ② 更新区
        pystray.MenuItem("检查助手更新", check_update_menu),
        pystray.MenuItem("下载并更新助手", download_update_menu,
                         enabled=lambda item: update_helper.UPDATE_READY is not None and getattr(sys, "frozen", False)),
        pystray.Menu.SEPARATOR,
        # ③ 默认入口（双击托盘）
        pystray.MenuItem("打开 opencodex 面板", on_open_dashboard, default=True),
        pystray.Menu.SEPARATOR,
        # ④ 服务控制（隧道）
        pystray.MenuItem("启动全部隧道", on_start_all),
        pystray.MenuItem("停止全部隧道", on_stop_all),
        pystray.Menu.SEPARATOR,
        # ⑤ 业务区
        pystray.MenuItem("穿透目标", build_targets_menu()),
        pystray.Menu.SEPARATOR,
        # ⑥ 服务控制（opencodex 本体）
        pystray.MenuItem("启动 opencodex 服务", on_ocx_start),
        pystray.MenuItem("停止 opencodex 服务", on_ocx_stop),
        pystray.MenuItem("重启 opencodex 服务", on_ocx_restart),
        pystray.Menu.SEPARATOR,
        # ⑦ 打开区
        pystray.MenuItem("打开 opencodex 目录", on_open_ocx_dir),
        pystray.MenuItem("打开助手日志目录", on_open_log),
        pystray.Menu.SEPARATOR,
        # ⑧ 偏好区
        pystray.MenuItem("开机自启", on_toggle_autostart,
                         checked=lambda item: autostart_enabled()),
        pystray.MenuItem("状态刷新间隔", build_probe_menu()),
        pystray.Menu.SEPARATOR,
        # ⑨ 退出（恒最后）
        pystray.MenuItem("退出", on_quit),
    )

def make_icon_image(connected):
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    color = (76, 175, 80) if connected else (158, 158, 158)
    d.ellipse((4, 4, 60, 60), fill=color)
    d.polygon([(32, 12), (48, 30), (39, 30), (39, 52), (25, 52), (25, 30), (16, 30)], fill=(255, 255, 255))
    return img

# ---------------- 开机自启 / ocx ----------------
RUN_KEY = r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "opencodex-helper"

def autostart_enabled():
    r = run_hidden(["reg", "query", RUN_KEY, "/v", RUN_NAME], capture_output=True, text=True)
    return r.returncode == 0

def set_autostart(on):
    exe = sys.executable if getattr(sys, "frozen", False) else str(Path(__file__).resolve())
    if on:
        run_hidden(["reg", "add", RUN_KEY, "/v", RUN_NAME, "/t", "REG_SZ", "/d", f'"{exe}"', "/f"],
                   capture_output=True)
    else:
        run_hidden(["reg", "delete", RUN_KEY, "/v", RUN_NAME, "/f"], capture_output=True)

def opencodex_home_dir():
    override = str(CFG.get("opencodex_home", "") or "").strip()
    if override:
        return str(Path(override).expanduser())
    env = os.environ.get("OPENCODEX_HOME", "").strip()
    if env:
        return str(Path(env).expanduser())
    return str(Path.home() / ".opencodex")

def ocx_cmd_path():
    """按优先级解析 ocx 命令：config 覆盖 -> 当前 npm prefix -> H:/Tools/npm -> 旧 APPDATA npm -> PATH。"""
    override = str(CFG.get("ocx_cmd", "") or "").strip()
    if override:
        p = Path(override).expanduser()
        if p.exists():
            return str(p)
    cands = []
    npm_prefix = os.environ.get("NPM_CONFIG_PREFIX", "").strip()
    if npm_prefix:
        cands.append(Path(npm_prefix) / "ocx.cmd")
    cands.append(Path(r"H:\Tools\npm") / "ocx.cmd")
    appdata = os.environ.get("APPDATA", "").strip()
    if appdata:
        cands.append(Path(appdata) / "npm" / "ocx.cmd")
    for c in cands:
        if c.exists():
            return str(c)
    found = shutil.which("ocx.cmd") or shutil.which("ocx")
    return found or "ocx"

def run_ocx(args, timeout):
    """执行 ocx 子命令；记录命令、返回码与输出尾部，失败/超时返回 None。"""
    cmd = ocx_cmd_path()
    full = [os.environ.get("COMSPEC", "cmd.exe"), "/c", cmd] + list(args)
    joined = " ".join(args)
    _log(f"ocx run: {cmd} {joined}")
    try:
        r = subprocess.run(full, capture_output=True, encoding="utf-8", errors="replace",
                           timeout=timeout, creationflags=CREATE_NO_WINDOW, cwd=HOME_DIR)
    except subprocess.TimeoutExpired as e:
        out = e.stdout or ""
        if isinstance(out, bytes):
            out = out.decode("utf-8", "replace")
        _log(f"ocx timeout: {joined} after {timeout}s out={str(out)[-300:]!r}")
        return None
    except Exception as e:
        _log(f"ocx run error: {joined}: {e}")
        return None
    _log(f"ocx result: {joined} rc={r.returncode} out={r.stdout.strip()[-300:]!r} err={r.stderr.strip()[-300:]!r}")
    return r

def ocx_health():
    """探测本机 opencodex：/healthz + /api/startup-health。"""
    base = str(CFG.get("dashboard_url", "http://127.0.0.1:10100")).rstrip("/")
    try:
        with urllib.request.urlopen(base + "/healthz", timeout=2) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        ok = bool(data and data.get("status") == "ok" and data.get("service") == "opencodex")
        port = data.get("port") if isinstance(data, dict) else None
        safety = None
        if ok:
            try:
                with urllib.request.urlopen(base + "/api/startup-health", timeout=2) as resp2:
                    sd = json.loads(resp2.read().decode("utf-8", "replace"))
                safety = sd.get("status") if isinstance(sd, dict) else None
            except Exception:
                safety = None
        return {"ok": ok, "port": port, "safety": safety}
    except Exception:
        return {"ok": False, "port": None, "safety": None}

_ocx_state = {"ok": False, "port": None, "safety": None}

def refresh_ocx_state(icon):
    h = ocx_health()
    changed = h != _ocx_state
    _ocx_state.update(h)
    if changed:
        _log(f"ocx health: ok={h['ok']} port={h['port']} safety={h['safety']}")
        refresh_icon(icon)
    return h

def ocx_status_line():
    if _ocx_state.get("ok"):
        return f"opencodex 服务: 在线 (端口 {_ocx_state.get('port') or '?'})"
    return "opencodex 服务: 离线"

def ocx_safety_line():
    s = _ocx_state.get("safety")
    if s == "at-risk":
        return "重启安全: 有风险"
    if s == "protected":
        return "重启安全: 已保护"
    if s:
        return "重启安全: 原生路由"
    return "重启安全: 不可用"

def ocx_start_service():
    _log("ocx action: start requested")
    r = run_ocx(["start"], 90)
    h = ocx_health()
    _ocx_state.update(h)
    if r is not None and r.returncode == 0 and h["ok"]:
        return True, f"opencodex 服务已启动（端口 {h['port']}）"
    detail = ""
    if r is not None:
        detail = (r.stderr.strip() or r.stdout.strip())[-200:]
    return False, f"opencodex 服务启动失败: {detail or '未知错误'}"

def ocx_stop_service():
    _log("ocx action: stop requested")
    r = run_ocx(["stop"], 60)
    h = ocx_health()
    _ocx_state.update(h)
    if r is not None and r.returncode == 0 and not h["ok"]:
        return True, "opencodex 服务已停止"
    detail = ""
    if r is not None:
        detail = (r.stderr.strip() or r.stdout.strip())[-200:]
    return False, f"opencodex 服务停止失败: {detail or '未知错误'}"

def ocx_restart_service():
    _log("ocx action: restart requested")
    r = run_ocx(["restart"], 180)
    h = ocx_health()
    _ocx_state.update(h)
    if r is not None and r.returncode == 0 and h["ok"]:
        return True, f"opencodex 服务已重启（端口 {h['port']}）"
    detail = ""
    if r is not None:
        detail = (r.stderr.strip() or r.stdout.strip())[-200:]
    return False, f"opencodex 服务重启失败: {detail or '未知错误'}"

def on_ocx_start(icon, item):
    threading.Thread(target=lambda: do_action(icon, ocx_start_service), daemon=True).start()

def on_ocx_stop(icon, item):
    threading.Thread(target=lambda: do_action(icon, ocx_stop_service), daemon=True).start()

def on_ocx_restart(icon, item):
    threading.Thread(target=lambda: do_action(icon, ocx_restart_service), daemon=True).start()

def on_open_ocx_dir(icon, item):
    d = opencodex_home_dir()
    _log(f"open opencodex dir: {d}")
    if os.path.isdir(d):
        os.startfile(d)  # noqa
    else:
        try:
            icon.notify(f"opencodex 目录不存在: {d}", APP_NAME)
        except Exception:
            pass

def do_action(icon, fn):
    ok, msg = fn()
    _log(f"action result: ok={ok} msg={msg}")
    try:
        icon.notify(msg, APP_NAME)
    except Exception:
        pass
    refresh_icon(icon)

def ocx_monitor_loop(icon):
    while True:
        time.sleep(5)
        try:
            refresh_ocx_state(icon)
        except Exception:
            pass

# ---------------- main ----------------
# 单实例：命名互斥体（T7 tray_kit；名字不含版本号，跨版本互拦）


def main():
    if not tray_kit.acquire_single_instance("opencodex-helper", log=_log):
        _log("another instance is already running; exiting")
        tray_kit.warn_duplicate_instance(APP_NAME,
                                         hint="请看任务栏右下角通知区域里的图标，本次启动已取消，不会多开一个托盘。")
        return 0
    _log(f"{APP_NAME} v{VERSION} starting (pid {os.getpid()})")
    if "--smoke" in sys.argv:
        print(f"version: {VERSION}")
        print(f"app: {APP_NAME}")
        print(f"config: {CONFIG_PATH}")
        print(f"config exists: {CONFIG_PATH.exists()}")
        print(f"targets: {len(CFG['targets'])}")
        for t in CFG["targets"]:
            print(f"  - {t['name']}  {conn_str(t)}  port={t.get('port',22)}  remote_port={t.get('remote_port')}  enabled={t.get('enabled',True)}")
        print(f"plink: {PLINK_PATH} exists={PLINK_PATH.exists()}")
        print(f"ssh-keygen: exists={Path(SSH_KEYGEN).exists()}")
        print(f"autostart: {autostart_enabled()}")
        print(f"ocx cmd: {ocx_cmd_path()} exists={Path(ocx_cmd_path()).exists()}")
        print(f"opencodex home: {opencodex_home_dir()}")
        h = ocx_health()
        print(f"ocx health: ok={h['ok']} port={h['port']} safety={h['safety']}")
        print("SMOKE OK")
        return 0

    threading.Thread(target=scan_all_tokens, daemon=True).start()
    threading.Thread(target=initial_probe_all, daemon=True).start()

    def startup_update_check():
        time.sleep(8)
        result = update_helper.check_update(VERSION, force=False)
        if result.get("newer"):
            try:
                icon.notify(f"发现新版本 {result['latest']}（当前 {VERSION}），右键菜单可下载更新", APP_NAME)
            except Exception:
                pass

    threading.Thread(target=startup_update_check, name="ocx-update-check", daemon=True).start()
    _ocx_state.update(ocx_health())
    _log(f"ocx initial health: ok={_ocx_state['ok']} port={_ocx_state['port']} safety={_ocx_state['safety']}")
    icon = pystray.Icon("opencodex-helper", icon=make_icon_image(False),
                        title=f"{APP_NAME} v{VERSION}", menu=build_menu())
    threading.Thread(target=monitor_loop, args=(icon,), daemon=True).start()
    threading.Thread(target=ocx_monitor_loop, args=(icon,), daemon=True).start()
    icon.run()
    return 0

if __name__ == "__main__":
    sys.exit(main())
