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
import queue
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

import pystray
from PIL import Image, ImageDraw

from modules import autostart, i18n, log_kit, paths, tray_kit, update_helper   # noqa: E402
from modules.appconfig import APP_ID   # noqa: E402
from modules.paths import APP_DIR, CONFIG_PATH, LOG_DIR, UPDATE_DIR, USER_DATA_DIR   # noqa: E402

# 程序本体目录**不在本文件派生**：唯一出处是 T2 paths 的 APP_DIR（打包后 = exe 所在
# 目录，开发态 = 仓库根）。这里曾另有一份同名派生量（开发态 = src/），与 paths 分叉，
# 只在冻结态碰巧重合——于是 dev 下 PLINK_PATH 解析成 src/bin/plink.exe 取不到，
# 而构建与冒烟全绿。
# 用户数据区/配置/日志/更新暂存同样出自 T2 paths（数据区住 LOCALAPPDATA，
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
VERSION = "1.2.1"

DEFAULT_CONFIG = {
    "targets": [],
    "local_port": 10100,
    "probe_interval_sec": 600,
    "ssh_connect_timeout_sec": 6,
    "probe_timeout_sec": 4,
    "dashboard_url": "http://127.0.0.1:10100",
    "ocx_cmd": "",
    "opencodex_home": "",
    # G4.2 条款 5：退出清理勾选，持久化、默认不勾——不勾 = 只停本工具启动的
    # 隧道（OWNED），外部手动启动的隧道不受影响（有界清理，条款 3/4）
    "quit_stop_tunnels": False,
}

LOG_DIR.mkdir(parents=True, exist_ok=True)
_logger = log_kit.get_logger(LOG_DIR)   # T12：滚动 1MB×3（house 标准 D13）


def _log(*parts):
    """模板件的日志契约是 **print 形态**（`log("下载中", name)`），与 log_kit 的单参闭包不同。

    `modules/update_helper` 里有 6 处多参调用；传单参的 log 进去，它们会在**真路径**上
    TypeError —— 而命中的正是"每次下载"(L407)、"每次成功拉起替换脚本"(L257)、
    "存在失败 marker 时"(L390) 这类必然会走到的行。opencodex 的更新链因此从来没跑通过。
    这里按契约收任意个参数再拼接（模板 log_kit 待 tpl-keeper 统一为同一形态）。
    """
    _logger.info(" ".join(str(part) for part in parts))

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
# T5：语言在配置读取之后、任何 t() 之前初始化（auto 跟随 Windows UI 语言）。
i18n.init(i18n.load_language_from_config(CONFIG_PATH))

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
            # G4.2 条款 5：勾选持久化随 save_config 走——漏写会让任何一次存盘
            # （改间隔/加目标等）把用户勾选抹回默认 False
            "quit_stop_tunnels": bool(CFG.get("quit_stop_tunnels", False)),
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
    """探测目标隧道是否健康。**失败方向 = 放行**（#45 / STANDARDS §D3.2）。

    返回值被用来决定 `kill_target_procs`（**杀用户正在用的那条隧道**），所以
    "探测**自身**出错"（ssh 不存在、超时、属性缺失）**不得**与"确定不健康"折叠成同一个
    `False` —— 那等于"我自己坏了就去拆用户的东西"，与本家族守卫类代码
    （`acquire_single_instance` / `mutex_name_is_valid`，失败一律放行）相反。

    **区分**（这是本函数唯一需要看懂的地方）：
    * `run_hidden` **返回非零**（ssh 连上了但握手/命令失败）⇒ 探测**跑成了** ⇒ 正常判 `False`；
    * `run_hidden` **抛异常**（超时 / 可执行文件缺失）⇒ 探测**没跑成** ⇒ `return True`（放行）
      并记一行日志。调用方据此不会误杀；代价是"真的坏了但探测也坏了"时会以为已连接
      —— 这正是 D3.2 选的失败侧（少一层判断 ≫ 拆用户的东西）。
    """
    key = target_key(t)
    remote = f"curl -sf -m {CFG['probe_timeout_sec']} http://127.0.0.1:{t.get('remote_port',10100)}/healthz"
    tok = _token_status.get(key)
    if tok is not False:
        try:
            r = run_hidden(ssh_args(t, [conn_str(t), remote]), capture_output=True, text=True,
                           timeout=CFG["ssh_connect_timeout_sec"] + CFG["probe_timeout_sec"] + 8)
            if r.returncode == 0 and '"service":"opencodex"' in r.stdout:
                return True
        except Exception as exc:
            _log(f"probe {t['name']}: ssh probe errored ({exc}) -> fail-open (not judged unhealthy, #45)")
            return True
    pw = _pw_cache.get(key)
    if pw and PLINK_PATH.exists():
        try:
            r = run_hidden(plink_args(t, pw, remote), capture_output=True, text=True,
                           timeout=CFG["ssh_connect_timeout_sec"] + CFG["probe_timeout_sec"] + 8)
            if r.returncode == 0 and '"service":"opencodex"' in r.stdout:
                return True
        except Exception as exc:
            _log(f"probe {t['name']}: plink probe errored ({exc}) -> fail-open (not judged unhealthy, #45)")
            return True
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
    """停止本 helper **自己启动**的该目标隧道（G4.2 条款 3：有界清理）。

    **只认 OWNED 句柄**（`_tunnel_procs`）——**不做命令行签名扫场**。
    G4.2 条款 3 明令「禁止全量签名击杀」：按 `cmdline` 特征（目标端口对 + conn_str）
    扫全场，会把**用户手动另起的同形隧道**一起杀掉，而那是条款 1 明文保护的业务自由
    （"helper 不阻止、不清理、不告警刷屏"）。**签名匹配无法区分"我们起的"与"别人起的"**
    —— 两者 cmdline 完全同形，没有可靠的自有判据：本进程只持有自己 Popen 的句柄；
    上一会话遗留的、用户手起的都只能算 ADOPTED（条款 4：放行是合法状态）。
    ⇒ 不为无法证明的所有权去拆用户的东西。

    ADOPTED 实例的显式停止属 service_link（B6）的优雅 API 路径；未接入前，"停止菜单"
    对外部实例**如实报停不下来**（probe 仍为真 ⇒ `stop_target` 返回失败），不假装成功。
    """
    key = target_key(t)
    proc = _tunnel_procs.pop(key, None)
    if proc:
        try:
            proc.terminate()
            _log(f"stop target {t['name']}: terminated owned tunnel (pid={proc.pid})")
        except Exception as exc:
            _log(f"stop target {t['name']}: owned tunnel terminate failed ({exc})")

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
        return False, i18n.t("tgt_connected_skip", t["name"])
    tok = _token_status.get(key)
    pw = _pw_cache.get(key)
    if tok is False and not pw:
        pw = ask_password(t)
        if not pw:
            _state[key] = False
            _log(f"start target {t['name']}: password required, cancelled")
            return False, i18n.t("tgt_need_password", t["name"])
        _pw_cache[key] = pw
    # #45 ①：清理陈旧隧道必须排在"确定要启动"**之后**。放在前面时，用户在口令框上
    # 按取消 → 我们一条隧道都没起，却已经把**用户正在用的那条**杀掉了 —— "我起不来
    # 却先动手拆"。这一格今天不影响本机（密钥可用 ⇒ probe 为真 ⇒ 上面就早退了），
    # 但口令型目标冷启动必然走到这里。
    kill_target_procs(t)
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
        return False, i18n.t("tgt_start_failed", t["name"], e)
    _tunnel_procs[key] = proc
    time.sleep(2.5)
    ok = probe_target(t)
    _state[key] = ok
    _log(f"start target {t['name']}: ok={ok}")
    return ok, i18n.t("tgt_connected", t["name"]) if ok else i18n.t("tgt_not_ready", t["name"])

def stop_target(t):
    key = target_key(t)
    if not probe_target(t):
        kill_target_procs(t)
        _state[key] = False
        _log(f"stop target {t['name']}: not running")
        return False, i18n.t("tgt_not_running_skip", t["name"])
    kill_target_procs(t)
    time.sleep(1)
    ok = probe_target(t)
    _state[key] = ok
    _log(f"stop target {t['name']}: stopped={not ok}")
    return not ok, i18n.t("tgt_stopped", t["name"]) if not ok else i18n.t("tgt_stop_failed", t["name"])

# ---------------- Tk 对话框 ----------------
def _tk_root(title):
    root = tk.Tk()
    root.title(title)
    root.attributes("-topmost", True)
    return root

def ask_password(t):
    try:
        root = _tk_root(i18n.t("dlg_password_title"))
        root.geometry("360x140")
        ttk.Label(root, text=i18n.t("dlg_password_target", t["name"], conn_str(t))).pack(padx=12, pady=(14, 4), anchor="w")
        ttk.Label(root, text=i18n.t("dlg_password_prompt")).pack(padx=12, pady=4, anchor="w")
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
        ttk.Button(frm, text=i18n.t("dlg_ok"), command=on_ok).pack(side="left", padx=8)
        ttk.Button(frm, text=i18n.t("dlg_cancel"), command=on_cancel).pack(side="left", padx=8)
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
    root = _tk_root(i18n.t("dlg_edit_target") if is_edit else i18n.t("dlg_add_target"))
    root.geometry("420x330")
    fields = [
        (i18n.t("field_name"), "name", "Ubuntu24.04"),
        (i18n.t("field_user"), "user", "xzy_admin"),
        (i18n.t("field_host"), "host", "192.168.190.128"),
        (i18n.t("field_ssh_port"), "port", "22"),
        (i18n.t("field_remote_port"), "remote_port", str(CFG.get("local_port", 10100))),
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
    ttk.Label(frm, text=i18n.t("dlg_key_label")).grid(row=len(fields), column=0, sticky="w", pady=3)
    vars_["key"] = tk.StringVar(value=str(t.get("key", "")) if is_edit else "")
    key_row = len(fields)
    ttk.Entry(frm, textvariable=vars_["key"], width=26).grid(row=key_row, column=1, sticky="w", pady=3)
    def browse_key():
        p = filedialog.askopenfilename(title=i18n.t("dlg_choose_key_title"), initialdir=str(Path.home() / ".ssh"))
        if p:
            vars_["key"].set(p)
    ttk.Button(frm, text=i18n.t("dlg_browse"), command=browse_key).grid(row=key_row, column=1, sticky="e", pady=3)
    # 本机已扫描到的密钥提示
    keys = scan_local_keys()
    if keys:
        ttk.Label(frm, text=i18n.t("dlg_local_keys", " / ".join(Path(k).name for k in keys)),
                  foreground="#666").grid(row=key_row + 1, column=0, columnspan=2, sticky="w", pady=2)
    vars_["enabled"] = tk.BooleanVar(value=t.get("enabled", True) if is_edit else True)
    ttk.Checkbutton(frm, text=i18n.t("dlg_enable_target"), variable=vars_["enabled"]).grid(
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
                messagebox.showwarning(i18n.t("dlg_warn_title"), i18n.t("dlg_host_required"), parent=root)
                return
            root.destroy()
        except Exception:
            messagebox.showerror(i18n.t("dlg_err_title"), i18n.t("dlg_port_number"), parent=root)
    def on_cancel():
        root.destroy()
    btns = ttk.Frame(root)
    btns.pack(pady=8)
    ttk.Button(btns, text=i18n.t("dlg_ok"), command=on_ok).pack(side="left", padx=8)
    ttk.Button(btns, text=i18n.t("dlg_cancel"), command=on_cancel).pack(side="left", padx=8)
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
    ttk.Button(btns, text=i18n.t("dlg_ok"), command=on_ok).pack(side="left", padx=8)
    ttk.Button(btns, text=i18n.t("dlg_cancel"), command=on_cancel).pack(side="left", padx=8)
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
    root = _tk_root(i18n.t("dlg_token_title"))
    ok = messagebox.askyesno(
        i18n.t("dlg_token_title"),
        i18n.t("dlg_token_confirm", t["name"], conn_str(t)),
        parent=root,
    )
    root.destroy()
    if not ok:
        return False, i18n.t("token_cancelled")
    key_path = Path.home() / ".ssh" / "id_ed25519"
    if key_path.exists():
        key_path = Path.home() / ".ssh" / "id_ed25519_opencodex_helper"
    key_path.parent.mkdir(parents=True, exist_ok=True)
    r = run_hidden([SSH_KEYGEN, "-t", "ed25519", "-f", str(key_path), "-N", "",
                    "-C", "opencodex-helper"],
                   capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        return False, i18n.t("token_keygen_failed", r.stderr.strip()[:200])
    pub = key_path.with_suffix(".pub").read_text(encoding="utf-8").strip()
    pw = ask_password(t)
    if not pw:
        return False, i18n.t("token_deploy_cancelled")
    _pw_cache[key] = pw
    ensure_plink_hostkey(t, pw)
    remote = ("mkdir -p ~/.ssh && chmod 700 ~/.ssh && touch ~/.ssh/authorized_keys && "
              "grep -qF -- {q} ~/.ssh/authorized_keys || echo {q} >> ~/.ssh/authorized_keys && "
              "chmod 600 ~/.ssh/authorized_keys").format(q=shlex.quote(pub))
    rd = run_hidden(plink_args(t, pw, remote), capture_output=True, text=True, timeout=25)
    if rd.returncode != 0:
        _log(f"deploy pubkey failed: {rd.stderr}")
        return False, i18n.t("token_deploy_failed", rd.stderr.strip()[:200])
    t["key"] = str(key_path)
    save_config()
    _token_status[key] = True
    return True, i18n.t("token_done", t["name"])

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
        d = ui_post(dialog_edit_target)   # 对话框含 tk.Tk() → 封送到 Tk 线程
        if d:
            CFG["targets"].append(d)
            save_config()
            _log(f"add target: {d['name']} {d['host']}")
            threading.Thread(target=lambda: scan_and_refresh(icon, [d]), daemon=True).start()
            try:
                icon.notify(i18n.t("notify_target_added", d["name"]), i18n.t("app_name"))
            except Exception:
                pass
    threading.Thread(target=_run, daemon=True).start()

def on_edit_target(icon, item):
    def _run():
        t = ui_post(lambda: pick_target(i18n.t("dlg_pick_edit")))
        if not t:
            return
        d = ui_post(lambda: dialog_edit_target(t))
        if d:
            t.update(d)
            save_config()
            _log(f"edit target: {t['name']} {t['host']}")
            refresh_icon(icon)
    threading.Thread(target=_run, daemon=True).start()

def on_delete_target(icon, item):
    def _run():
        def _ask():
            t = pick_target(i18n.t("dlg_pick_delete"))
            if not t:
                return None
            root = _tk_root(i18n.t("dlg_delete_title"))
            ok = messagebox.askyesno(i18n.t("dlg_delete_title"), i18n.t("dlg_delete_confirm", t["name"], t["host"]), parent=root)
            root.destroy()
            return t if ok else None

        t = ui_post(_ask)    # 选目标 + 确认框都在 Tk 线程上跑（E1-03/I-03）
        if not t:
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
        pick = ui_post(lambda: cand[0] if len(cand) == 1
                       else pick_target(i18n.t("dlg_pick_token")))
        if not pick:
            return
        ok, msg = ui_post(lambda: generate_token_for_target(pick))
        _log(f"generate token {pick['name']}: ok={ok} msg={msg}")
        try:
            icon.notify(msg, i18n.t("app_name"))
        except Exception:
            pass
        refresh_icon(icon)
    threading.Thread(target=_run, daemon=True).start()

def on_rescan_tokens(icon, item):
    def _run():
        scan_all_tokens()
        refresh_icon(icon)
        try:
            icon.notify(i18n.t("notify_token_scan_done"), i18n.t("app_name"))
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
    enabled = not autostart.is_autostart_enabled()
    autostart.set_autostart(enabled)
    _log(f"autostart -> {autostart.is_autostart_enabled()}")
    refresh_icon(icon)

def on_toggle_language(icon, item):
    """中英切换（T1）：改语言 → 持久化 → 显式重建菜单（D14）。"""
    new_lang = "en" if i18n.current_lang() == "zh" else "zh"
    i18n.init(new_lang)
    i18n.save_language_to_config(CONFIG_PATH, new_lang)
    _log(f"language switched: {new_lang}")
    try:
        icon.notify(i18n.t("notify_lang_switched"), i18n.t("app_name"))
    except Exception:
        pass
    try:
        icon.menu = build_menu()
        icon.update_menu()
    except Exception as exc:
        _log(f"menu rebuild after language switch failed: {exc}")

def on_open_dashboard(icon, item):
    _log(f"open dashboard: {CFG['dashboard_url']}")
    webbrowser.open(CFG["dashboard_url"])

def on_open_log(icon, item):
    os.startfile(str(LOG_DIR))  # noqa

def on_quit(icon, item):
    # G4.1 条款 4：退出必须过确认框；取消/关窗不退出。
    # 降级链：富对话框 → 原生 askyesno → 链路不可用时放行退出（服务不动）。
    def _decide_quit():
        """退出确认裁决 → (proceed, stop_service)。**三态必须分开**。

        2026-09-19 缺陷：链路不可用（None）与用户明确取消（{"go": False}）共用一个
        `return`，于是弹窗一坏用户就被锁死在工具里——ocx 1.2.2 实证：_internal 目录
        被掏空、Tk 读不到 init.tcl，点「退出」静默无反应，只能用任务管理器。
        「不可用 ⇒ 放行」不等于「默认 True」：确认框本身没被拆掉，问到就一定听用户的。
        """
        try:
            def _persist_quit_stop(value: bool) -> None:
                # G4.2 条款 5（2026-09-18 用户定）：勾选一变即持久化，不等「退出」点击
                CFG["quit_stop_tunnels"] = bool(value)
                save_config()

            # 确认框要建 Tk 根 → 封送到唯一的 Tk 线程（E1-03/I-03）。
            # 降级链两级都在里面跑：富对话框失败就走原生 askyesno（同样在那一个线程上）。
            def _confirm():
                try:
                    return tray_kit.confirm_quit_dialog(
                        i18n.t("app_name"), i18n.t("quit_checkbox"),
                        bool(CFG.get("quit_stop_tunnels", False)),
                        on_change=_persist_quit_stop,
                        body_text=i18n.t("quit_native_text"),
                        confirm_text=i18n.t("quit_confirm_yes"),
                        cancel_text=i18n.t("quit_confirm_no"))
                except Exception as exc:
                    _log(f"quit dialog failed ({type(exc).__name__}: {exc}); "
                         f"falling back to native confirm")
                try:
                    import tkinter as _tk
                    from tkinter import messagebox as _mb
                    _root = _tk.Tk()
                    _root.withdraw()
                    _go = bool(_mb.askyesno(i18n.t("app_name"), i18n.t("quit_native_text")))
                    _root.destroy()
                    return {"go": _go, "stop_service": bool(CFG.get("quit_stop_tunnels", False))}
                except Exception as exc2:
                    # Tk 运行时缺失 / 会话不可交互：这**不是**用户作答，交给调用方放行。
                    _log(f"native confirm failed ({type(exc2).__name__}: {exc2})")
                    return None

            choice = ui_post(_confirm)
        except Exception as exc:
            _log(f"quit confirm could not be marshalled ({type(exc).__name__}: {exc})")
            return True, False         # 链路不可用 ⇒ 放行退出，服务不动
        if choice is None:
            _log("quit confirm unavailable; quitting without stopping the service")
            return True, False         # 同上：弹窗链路整个不可用
        if not choice.get("go"):
            _log("quit cancelled by user")
            return False, False        # 用户明确取消 ⇒ 不退出（确认框照旧有效）
        return True, bool(choice.get("stop_service"))

    _proceed, stop_tunnels = _decide_quit()   # 持久化已随勾选动作完成
    if not _proceed:
        return
    if stop_tunnels:
        # 用户勾选「顺便关闭隧道」⇒ 对各目标走有界清理。**作用域 = 接入实例（G4.2 条款 5）**：
        # `kill_target_procs` 只终止 OWNED 句柄，**不再做命令行签名扫场**（条款 3 禁全量击杀）
        # ⇒ 用户手动另起的同形隧道**不被碰**（条款 1 业务自由）。
        for t in CFG["targets"]:
            kill_target_procs(t)
    else:
        # G4.2 **条款 5**：不勾选 = 服务与隧道**越过托盘生命周期继续运行**（明文）。
        # ⚠ 旧实现（至 1.2.1）在这里 terminate 了**所有 OWNED 句柄** ⇒ 用户报告
        #   （2026-09-20）："没选关闭隧道，结果也关了"。
        # 根因是**把条款 3 的"作用域规则"当成了"触发条件"**：
        #   · 条款 5 管「**要不要**清理」——由本勾选框决定（默认不勾 ⇒ 不清）；
        #   · 条款 3 管「**清理谁**」——作用域 = 接入实例、禁全量签名击杀（不勾时根本用不上）。
        # 两者分工，不可互推。OWNED 隧道同样是"服务越过托盘继续运行"的一种（条款 4：
        # 放行是合法状态，不是泄漏），下次启动由探测自动重新接入。
        _log("quit: tunnels keep running (checkbox not ticked, G4.2-5); "
             "owned handles released with this process")
    icon.stop()
    if PENDING_UPDATE_CMD:
        # 本进程退出后由脚本接管：等待 → robocopy 铺新版 → 重启新 exe → 自删。
        # 走 update_helper 的收尾件，不用 os.system('start …')：后者经 cmd 新建控制台，
        # 本进程是没有控制台的 GUI，退出时桌面会闪一下黑框；它还是 shell 字符串插值。
        # 该件用 CREATE_NO_WINDOW|DETACHED_PROCESS 让脚本脱离父进程继续跑完替换。
        if not update_helper.launch_pending_cmd(PENDING_UPDATE_CMD, log=_log):
            _log("quit: pending update script was NOT launched")

# ---------------- 托盘 / 菜单 ----------------
# E2-09：签名重画 + 菜单占用探测。旧形态每处状态变更都无条件 icon.update_menu()，
# 而 pystray 的重建是 DestroyMenu + CreatePopupMenu：菜单正开着时重建 = 把它从用户
# 手底下抽走（鼠标滑着滑着突然失焦）。改成：状态提成签名 → 只有签名变了才重建 →
# 菜单开着时推迟，由 1.5s 补画拍补上。
GUI_INMENUMODE = 0x00000004
_TRAY_ICON = None


def menu_is_open():
    """系统弹出菜单是否正开着（E2-09）。

    探测：菜单模态标记 GUI_INMENUMODE 挂在**调用 TrackPopupMenu 的那个线程**上，
    遍历本进程线程去问；再以「前台窗口是系统菜单类 #32768」兜底。探测失败当没开着
    （宁可多重建一次，也不能因为探测失败就永远不重建）。
    """
    if os.name != "nt":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        class GUITHREADINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD),
                        ("hwndActive", wintypes.HWND), ("hwndFocus", wintypes.HWND),
                        ("hwndCapture", wintypes.HWND), ("hwndMenuOwner", wintypes.HWND),
                        ("hwndMoveSize", wintypes.HWND), ("hwndCaret", wintypes.HWND),
                        ("rcCaret", wintypes.RECT)]

        user32 = ctypes.windll.user32
        for thread in threading.enumerate():
            tid = getattr(thread, "native_id", None)
            if not tid:
                continue
            info = GUITHREADINFO()
            info.cbSize = ctypes.sizeof(GUITHREADINFO)
            if not user32.GetGUIThreadInfo(int(tid), ctypes.byref(info)):
                continue
            if info.flags & GUI_INMENUMODE:
                return True
        hwnd = user32.GetForegroundWindow()
        if hwnd:
            name = ctypes.create_unicode_buffer(32)
            user32.GetClassNameW(hwnd, name, 32)
            if name.value == "#32768":
                return True
    except Exception:
        return False
    return False


def _menu_signature():
    """菜单上会「显示出来」的全部状态：只有它变了才值得重建（E2-09/§D6）。

    **漏一项 = 那一项变了菜单不刷新**。逐项对照 build_menu()：
      · 隧道信息行 status_line() ← 每个目标的（key / 名字 / 地址 / 启用 / 连通 / 令牌）
      · opencodex 在线行与安全行 ← _ocx_state
      · 「下载并更新」的 enabled ← LATEST_VERSION
      · 自启的 checked ← 注册表
      · 探测间隔子菜单的 checked ← CFG
      · 全部菜单文案 ← i18n.current_lang()
    目标的 name/host 也在签名里——改名或改地址同样要让菜单重画。
    """
    with _lock:
        tunnels = tuple(
            (target_key(t), t.get("name"), t.get("host"), bool(t.get("enabled", True)),
             bool(_state.get(target_key(t))), _token_status.get(target_key(t)))
            for t in CFG["targets"]
        )
    return (
        i18n.current_lang(),
        tunnels,
        tuple(sorted(_ocx_state.items())),
        LATEST_VERSION is not None,
        autostart.is_autostart_enabled(),
        CFG.get("probe_interval_sec", 600),
    )


def rebuild_menu():
    """MenuSignature 的落地动作：真正重画图标与菜单句柄（只由签名变化驱动）。"""
    icon = _TRAY_ICON
    if icon is None:
        return
    with _lock:
        connected = global_connected_count() > 0
    icon.icon = make_icon_image(connected)
    icon.menu = build_menu()
    icon.update_menu()


MENU_SIG = tray_kit.MenuSignature(rebuild_menu, menu_is_open=menu_is_open, log=_log)


def refresh_icon(icon):
    """状态变了就重画；菜单开着时自动推迟（由 menu_refresh_loop 的补画拍补上）。

    调用点遍布状态变更处，保持原签名不变——只是从「每次都重建」变成「签名变了才重建」。
    """
    MENU_SIG.update(_menu_signature())


def menu_refresh_loop():
    """1.5s 补画拍（tray_kit 三循环之②）：把「菜单开着时被推迟」的那次重画补上。"""
    while True:
        time.sleep(1.5)
        try:
            refresh_icon(_TRAY_ICON)
            MENU_SIG.flush_deferred()
        except Exception as exc:
            _log(f"menu refresh failed: {exc}")


# ---- E1-03 / I-03：UI 队列封送 -------------------------------------------------
# tkinter 不是线程安全的，而本工具的对话框是在 threading.Thread 里弹的（为了不让托盘
# 在等用户操作时失去响应）。此前那等于**在工作线程里建/毁一个 Tk 解释器**——换一个
# CPython/_tkinter 构建就可能崩，任何跨线程共享都会踩解释器状态。
# 改成：**所有 Tk 工作都投给同一个常驻线程**，工作线程投完等结果回来。
# 跨线程传递的只有「队列里的一个可调用对象」，Tk 对象从不离开它自己的线程。
ui_q = queue.Queue()
_UI_THREAD_NAME = "ocx-ui"
_ui_start_lock = threading.Lock()
_ui_thread = None


def ui_thread_loop():
    """唯一的 Tk 线程：顺序执行投进来的 UI 工作（daemon，进程退出即结束）。"""
    while True:
        ui_q.get()()


def ui_post(fn):
    """把 UI 工作封送到唯一的 Tk 线程执行，阻塞取回结果（E1-03/I-03）。

    线程**按需启动**：不经过 main() 的路径（测试、诊断）若只 put 不执行会永久卡在
    done.wait()。已在 Tk 线程上时直接跑，避免自己投的活自己等。
    """
    global _ui_thread
    if threading.current_thread().name == _UI_THREAD_NAME:
        return fn()
    with _ui_start_lock:
        if _ui_thread is None or not _ui_thread.is_alive():
            _ui_thread = threading.Thread(target=ui_thread_loop, name=_UI_THREAD_NAME,
                                          daemon=True)
            _ui_thread.start()

    box, done = {}, threading.Event()

    def _job():
        try:
            box["result"] = fn()
        except BaseException as exc:    # 异常要原样回到调用方，不能吞成静默
            box["exc"] = exc
        finally:
            done.set()

    ui_q.put(_job)
    done.wait()
    if "exc" in box:
        raise box["exc"]
    return box.get("result")


def notify_status_change(icon, name, ok):
    msg = i18n.t("tunnel_connected", name) if ok else i18n.t("tunnel_disconnected", name)
    try:
        icon.notify(msg, i18n.t("app_name"))
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
        icon.notify(i18n.t("notify_interval_set", seconds), i18n.t("app_name"))
    except Exception:
        pass

PROBE_CHOICES = [(20, "probe_20s"), (60, "probe_1m"), (300, "probe_5m"), (600, "probe_10m"),
                 (1800, "probe_30m"), (3600, "probe_1h")]

def build_probe_menu():
    return pystray.Menu(*[
        pystray.MenuItem(i18n.t(key), functools.partial(save_config_set_probe, seconds=sec),
                         checked=lambda item, s=sec: CFG.get("probe_interval_sec", 600) == s)
        for sec, key in PROBE_CHOICES
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
    items.append(pystray.MenuItem(i18n.t("menu_add_target"), on_add_target))
    items.append(pystray.MenuItem(i18n.t("menu_edit_target"), on_edit_target))
    items.append(pystray.MenuItem(i18n.t("menu_delete_target"), on_delete_target))
    items.append(pystray.MenuItem(i18n.t("menu_gen_token"), on_generate_token))
    items.append(pystray.MenuItem(i18n.t("menu_rescan_tokens"), on_rescan_tokens))
    return pystray.Menu(*items)

def status_line():
    n = global_connected_count()
    e = enabled_count()
    return i18n.t("status_tunnels_connected", n, e) if n else i18n.t("status_tunnels_down")

# 更新状态由**工具自持**，不读模板模块的可变全局（模板包曾 import * 拷死 PENDING_CMD
# → apply.cmd 永不拉起；UPDATE_READY 曾恒 None → "下载并更新"恒灰）。稳定契约是返回值：
# check_update() -> {"newer", "latest", ...}；download_and_prepare() -> 脚本路径。
LATEST_VERSION = None
PENDING_UPDATE_CMD = None


def check_update_menu(_icon=None, _item=None):
    def worker():
        global LATEST_VERSION
        result = update_helper.check_update(VERSION, force=True)
        if result.get("newer"):
            LATEST_VERSION = result["latest"]
            notify_status_change(_icon, i18n.t("notify_update_available", result["latest"], VERSION), True)
        elif result.get("error"):
            # 网络失败不动既有状态，避免误清已发现的新版本
            notify_status_change(_icon, i18n.t("notify_update_check_failed", result["error"]), False)
        else:
            LATEST_VERSION = None
            notify_status_change(_icon, i18n.t("notify_update_latest", VERSION), True)
        try:
            _icon.update_menu()
        except Exception:
            pass
    threading.Thread(target=worker, daemon=True).start()


def download_update_menu(_icon=None, _item=None):
    global PENDING_UPDATE_CMD
    latest = LATEST_VERSION
    if not latest or not getattr(sys, "frozen", False):
        return

    def worker():
        global PENDING_UPDATE_CMD
        try:
            PENDING_UPDATE_CMD = update_helper.download_and_prepare(latest, APP_DIR, UPDATE_DIR, log=_log)
            _icon.notify(i18n.t("notify_update_ready"), i18n.t("app_name"))
        except Exception as e:
            _log(f"update download failed: {e}")
            _icon.notify(i18n.t("notify_update_download_failed", e), i18n.t("app_name"))
        try:
            _icon.update_menu()
        except Exception:
            pass
    threading.Thread(target=worker, daemon=True).start()


def build_menu():
    """house 标准八段式（执行文档 D14）：信息 → 更新 → 默认入口 → 服务控制 → 业务 → 打开 → 偏好 → 退出。"""
    return pystray.Menu(
        # ① 信息区（只读；此前 ocx 状态行错位在菜单中部，本次归位到顶上）
        pystray.MenuItem(lambda item: f'{i18n.t("app_name")} v{VERSION}', None, enabled=False),
        pystray.MenuItem(lambda item: status_line(), None, enabled=False),
        pystray.MenuItem(lambda item: ocx_status_line(), None, enabled=False),
        pystray.MenuItem(lambda item: ocx_safety_line(), None, enabled=False),
        pystray.Menu.SEPARATOR,
        # ② 更新区
        pystray.MenuItem(i18n.t("menu_check_update"), check_update_menu),
        pystray.MenuItem(i18n.t("menu_update_now"), download_update_menu,
                         enabled=lambda item: LATEST_VERSION is not None and getattr(sys, "frozen", False)),
        pystray.Menu.SEPARATOR,
        # ③ 默认入口（双击托盘）
        pystray.MenuItem(i18n.t("menu_open_dashboard"), on_open_dashboard, default=True),
        pystray.Menu.SEPARATOR,
        # ④ 服务控制（隧道）
        pystray.MenuItem(i18n.t("menu_start_all"), on_start_all),
        pystray.MenuItem(i18n.t("menu_stop_all"), on_stop_all),
        pystray.Menu.SEPARATOR,
        # ⑤ 业务区
        pystray.MenuItem(i18n.t("menu_targets"), build_targets_menu()),
        pystray.Menu.SEPARATOR,
        # ⑥ 服务控制（opencodex 本体）
        pystray.MenuItem(i18n.t("menu_ocx_start"), on_ocx_start),
        pystray.MenuItem(i18n.t("menu_ocx_stop"), on_ocx_stop),
        pystray.MenuItem(i18n.t("menu_ocx_restart"), on_ocx_restart),
        pystray.Menu.SEPARATOR,
        # ⑦ 打开区
        pystray.MenuItem(i18n.t("menu_open_ocx_dir"), on_open_ocx_dir),
        pystray.MenuItem(i18n.t("menu_open_logs"), on_open_log),
        pystray.Menu.SEPARATOR,
        # ⑧ 偏好区
        pystray.MenuItem(i18n.t("menu_autostart"), on_toggle_autostart,
                         checked=lambda item: autostart.is_autostart_enabled()),
        pystray.MenuItem(i18n.t("menu_refresh_interval"), build_probe_menu()),
        pystray.MenuItem(i18n.t("menu_language"), on_toggle_language),
        pystray.Menu.SEPARATOR,
        # ⑨ 退出（恒最后）
        pystray.MenuItem(i18n.t("menu_quit"), on_quit),
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
# 自启三件套（含稳定位指向与启动自愈）全部来自 T3 模板件 modules/autostart。
# 注册表键名 = appconfig.APP_NAME（"opencodex-helper"，与历史键一致，换名=断链）。

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
        return i18n.t("ocx_status_online", _ocx_state.get("port") or "?")
    return i18n.t("ocx_status_offline")

def ocx_safety_line():
    s = _ocx_state.get("safety")
    if s == "at-risk":
        return i18n.t("safety_at_risk")
    if s == "protected":
        return i18n.t("safety_protected")
    if s:
        return i18n.t("safety_native")
    return i18n.t("safety_unavailable")

def ocx_start_service():
    _log("ocx action: start requested")
    r = run_ocx(["start"], 90)
    h = ocx_health()
    _ocx_state.update(h)
    if r is not None and r.returncode == 0 and h["ok"]:
        return True, i18n.t("ocx_started", h["port"])
    detail = ""
    if r is not None:
        detail = (r.stderr.strip() or r.stdout.strip())[-200:]
    return False, i18n.t("ocx_start_failed", detail or i18n.t("err_unknown"))

def ocx_stop_service():
    _log("ocx action: stop requested")
    r = run_ocx(["stop"], 60)
    h = ocx_health()
    _ocx_state.update(h)
    if r is not None and r.returncode == 0 and not h["ok"]:
        return True, i18n.t("ocx_stopped")
    detail = ""
    if r is not None:
        detail = (r.stderr.strip() or r.stdout.strip())[-200:]
    return False, i18n.t("ocx_stop_failed", detail or i18n.t("err_unknown"))

def ocx_restart_service():
    _log("ocx action: restart requested")
    r = run_ocx(["restart"], 180)
    h = ocx_health()
    _ocx_state.update(h)
    if r is not None and r.returncode == 0 and h["ok"]:
        return True, i18n.t("ocx_restarted", h["port"])
    detail = ""
    if r is not None:
        detail = (r.stderr.strip() or r.stdout.strip())[-200:]
    return False, i18n.t("ocx_restart_failed", detail or i18n.t("err_unknown"))

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
            icon.notify(i18n.t("notify_ocx_dir_missing", d), i18n.t("app_name"))
        except Exception:
            pass

def do_action(icon, fn):
    ok, msg = fn()
    _log(f"action result: ok={ok} msg={msg}")
    try:
        icon.notify(msg, i18n.t("app_name"))
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


def smoke():
    """冻结冒烟（D3-01 旁路）：**不抢互斥体、不写注册表、不启动托盘**。

    必须在 main() 的 acquire_single_instance 之前调用——否则用户常驻实例在跑时
    冒烟会拿不到互斥体，转而走重复启动提示（模态 MessageBox，会把构建挂死）。
    """
    # D3.1 / C-10 守卫覆盖探针：名字合法性（不占锁、不弹窗），须与运行期守卫同名。
    if not tray_kit.mutex_name_is_valid(APP_ID):
        print("FAIL mutex name is illegal for %s" % APP_ID)
        return 1
    print(f"mutex name ok: {APP_ID}")
    print(f"version: {VERSION}")
    print(f"app: {APP_NAME}")
    print(f"config: {CONFIG_PATH}")
    print(f"config exists: {CONFIG_PATH.exists()}")
    print(f"targets: {len(CFG['targets'])}")
    for t in CFG["targets"]:
        print(f"  - {t['name']}  {conn_str(t)}  port={t.get('port',22)}  remote_port={t.get('remote_port')}  enabled={t.get('enabled',True)}")
    print(f"plink: {PLINK_PATH} exists={PLINK_PATH.exists()}")
    print(f"ssh-keygen: exists={Path(SSH_KEYGEN).exists()}")
    print(f"autostart: {autostart.is_autostart_enabled()}")
    print(f"ocx cmd: {ocx_cmd_path()} exists={Path(ocx_cmd_path()).exists()}")
    print(f"opencodex home: {opencodex_home_dir()}")
    h = ocx_health()
    print(f"ocx health: ok={h['ok']} port={h['port']} safety={h['safety']}")
    print("SMOKE OK")
    return 0


def main():
    global _TRAY_ICON
    if not tray_kit.acquire_single_instance("opencodex-helper", log=_log):
        _log("another instance is already running; exiting")
        tray_kit.warn_duplicate_instance(
            i18n.t("app_name"),
            message="\n\n".join([i18n.t("dup_running"),
                                  i18n.t("dup_hint")]))
        return 0
    _log(f"{APP_NAME} v{VERSION} starting (pid {os.getpid()})")
    # T2/C-2（paths 1.1.4，MUST-WIRE）：让"本实例的 exe 不可被删除/改名"由**内核**保证，
    # 而不是由纪律保证。持有的是一个**不含 FILE_SHARE_DELETE** 的句柄 ⇒ 删除方（构建脚本 /
    # 手工 `rm -r` / 未来的 --clean）会**大声失败**，而不是把正在运行的实例目录静默掏空
    # （2026-09-19 事故的形态：实例仍在其中运行时 release\<工具>-<版本>\ 被掏空）。
    # 必须在**托盘创建之前**调用——晚一步，那一步的窗口期就没有保护；句柄持有到进程结束
    # （故意不 close，寿命就是进程寿命）；拿不到只记一行日志，绝不拦住启动（D3.2）；
    # dev 态由模板自己跳过（保护 python.exe 无意义）。
    paths.hold_exe_delete_guard(log=_log)

    # G4.1 条款 3/5：启动自愈——存量 Run 键指向的 exe 已消失（换版本目录被删）时，
    # 静默重写到当前正确位置（优先稳定安装位 INSTALL_EXE，见 modules/autostart）。
    # 放在 --smoke 早退之后：冒烟是只读检查，不得改写用户真实注册表（D3-03）。
    autostart.migrate_autostart(log=_log)
    # T4 收尾：更新脚本在托盘退出后才跑，要是被打断（重启/被杀/半路消失），那份解压好的
    # 整包（实测 ~50MB/次）就烂在 %TEMP% 里没人知道——启动扫一次。只清一小时前的：
    # 正在进行的更新，其暂存目录是刚建的。清扫失败不抛，拦不住启动。
    swept = update_helper.sweep_stale_update_dirs()
    if swept:
        _log(f"update housekeeping: swept {swept} stale update dir(s) from TEMP")
    # T4 收尾：上次更新失败的通知也只能等下次启动说（更新脚本自删了）。marker 读一次即删，
    # 所以先取出来；图标还没 run、通知发不出去，先留在闭包里，到 setup 回调再发。
    # 模板返回的是中文人话串（详情它已自己写进 update.log），这里只取"失败过"这个事实，
    # 文案走 i18n，否则英文界面会弹出一句中文（T1 回归）。
    failed_note = update_helper.pop_failed_update_note(UPDATE_DIR, log=_log)

    threading.Thread(target=scan_all_tokens, daemon=True).start()
    threading.Thread(target=initial_probe_all, daemon=True).start()

    def startup_update_check():
        global LATEST_VERSION
        time.sleep(8)
        result = update_helper.check_update(VERSION, force=False)
        if result.get("newer"):
            LATEST_VERSION = result["latest"]
            try:
                icon.notify(i18n.t("notify_update_available_menu", result["latest"], VERSION), i18n.t("app_name"))
            except Exception:
                pass

    threading.Thread(target=startup_update_check, name="ocx-update-check", daemon=True).start()
    _ocx_state.update(ocx_health())
    _log(f"ocx initial health: ok={_ocx_state['ok']} port={_ocx_state['port']} safety={_ocx_state['safety']}")
    icon = pystray.Icon("opencodex-helper", icon=make_icon_image(False),
                        title=f'{i18n.t("app_name")} v{VERSION}', menu=build_menu())
    _TRAY_ICON = icon   # MenuSignature 的重建动作要用（状态变更处只调 refresh_icon）
    threading.Thread(target=monitor_loop, args=(icon,), daemon=True).start()
    threading.Thread(target=ocx_monitor_loop, args=(icon,), daemon=True).start()
    # E2-09 第②拍：菜单开着时被推迟的重画在这里补上（探针间隔最长 30 分钟，不能靠它）。
    threading.Thread(target=menu_refresh_loop, name="ocx-menu-refresh", daemon=True).start()

    def _setup_tray(_icon):
        # 传入自定义 setup 后，pystray 不会再自动设置 visible=True。
        # 必须显式显示图标，否则进程会常驻但托盘中看不到入口。
        _icon.visible = True
        # 上次更新失败的通知：早退、无托盘时不提示，只有真起来了才说（见 main() 里的注释）。
        if failed_note:
            try:
                _icon.notify(i18n.t("notify_update_failed_prev"), i18n.t("app_name"))
            except Exception:
                pass

    icon.run(setup=_setup_tray)
    return 0

def lang_audit():
    """T5/T1 自检（--lang-audit）：静态扫描本文件里未进 zh 词表的中文串。

    只查字面量（docstring 除外），命中即列出行号；退出码非 0 = 有遗漏。
    数据/标识符本就不该进词表，故只在 src/main.py 上跑。
    """
    import ast
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    source_path = Path(__file__)
    if not source_path.is_file():
        print(f"lang-audit: source not available in frozen build ({source_path.name})")
        print(f"lang-audit: loaded tables zh={len(i18n.TABLES['zh'])} en={len(i18n.TABLES['en'])}")
        return 0
    source = source_path.read_text(encoding="utf-8")
    known = set(i18n.TABLES["zh"].values())
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        print(f"FAIL lang-audit: {exc}")
        return 1
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", None)
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                docstrings.add(id(body[0].value))
    missing = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if id(node) in docstrings:
            continue
        if any(0x4E00 <= ord(ch) <= 0x9FFF for ch in node.value) and node.value not in known:
            missing.append((node.lineno, node.value))
    for lineno, text in sorted(missing):
        print(f"MISSING L{lineno}: {text}")
    print(f"lang-audit: {len(missing)} untranslated Chinese literal(s); zh table={len(known)} values")
    return 1 if missing else 0


if __name__ == "__main__":
    if "--lang-audit" in sys.argv:
        sys.exit(lang_audit())
    if "--smoke" in sys.argv:
        sys.exit(smoke())
    sys.exit(main())
