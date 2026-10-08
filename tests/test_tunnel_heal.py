# -*- coding: utf-8 -*-
"""隧道自愈语义：N=3 确认 / 退避门 / 密码型不自动重连。

全部假目标（不可达端口），零真实 ssh/隧道接触（红线：测试不碰在用隧道）。
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import main as M  # noqa: E402
from template.tunnel_kit import tunnel_kit  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(("  ok  " if ok else "  FAIL") + " " + name + ("  " + str(detail) if not ok else ""), flush=True)
    if not ok:
        FAILS.append(name)


# ---- ① 命令行段（密钥型隧道长连接） ----
t = {"name": "probe-target", "user": "u", "host": "127.0.0.1", "port": 1,
     "remote_port": 1, "key": "k.pem", "enabled": True}
M.CFG["local_port"] = 10100
cmd = M._key_tunnel_cmd(t)
check("命令行含 ExitOnForwardFailure=yes", "ExitOnForwardFailure=yes" in cmd)
check("命令行含 ServerAliveInterval=30 / CountMax=3",
      "ServerAliveInterval=30" in cmd and "ServerAliveCountMax=3" in cmd)
check("命令行含 -N 与 -R 段", "-N" in cmd and "-R" in cmd)
check("-R 端口段形态", cmd[cmd.index("-R") + 1] == "1:127.0.0.1:10100")

# ---- ② N=3 确认：前两次不动手 ----
calls = {"n": 0}
M._token_status[M.target_key(t)] = True


def fake_start(tt):
    calls["n"] += 1
    return True, "started"


orig_start = M.start_target
M.start_target = fake_start
try:
    M._heal.pop(M.target_key(t), None)
    M.ensure_target_healed(t)
    M.ensure_target_healed(t)
    check("前 2 次失败不重连（unconfirmed）", calls["n"] == 0, calls)
    # ③ 第 3 次触发重连；退避门：确认后立即再判死 → 不再连（next_retry 未到）
    M.ensure_target_healed(t)
    check("第 3 次确认后重连", calls["n"] == 1, calls)
    M._heal[M.target_key(t)]["streak"] = tunnel_kit.DEFAULTS["confirm_n"]  # 直接置满
    M.ensure_target_healed(t)
    check("退避门拦截（刚连过不再连）", calls["n"] == 1, calls)
    M._heal[M.target_key(t)]["next_retry"] = 0.0
    M.ensure_target_healed(t)
    check("退避到期后再连", calls["n"] == 2, calls)
finally:
    M.start_target = orig_start

# ---- ③b （09-29）：连续失败重连 → 退避翻倍；成功复位 ----
M._token_status[M.target_key(t)] = True
calls2 = {"n": 0}


def failing_start(tt):
    calls2["n"] += 1
    return False, "start failed"


M.start_target = failing_start
try:
    M._heal.pop(M.target_key(t), None)
    M.ensure_target_healed(t)          # 先走一拍让 setdefault 建键（unconfirmed 早退）
    for expect in (60.0, 120.0, 240.0):
        hh = M._heal[M.target_key(t)]
        hh["streak"] = tunnel_kit.DEFAULTS["confirm_n"]
        hh["next_retry"] = 0.0
        M.ensure_target_healed(t)
        got = M._heal[M.target_key(t)]["backoff"]
        check(f"失败重连后退避翻倍至 {expect:.0f}s", got == expect, got)
    M.start_target = fake_start
    hh = M._heal[M.target_key(t)]
    hh["streak"] = tunnel_kit.DEFAULTS["confirm_n"]
    hh["next_retry"] = 0.0
    M.ensure_target_healed(t)
    check("重连成功后退避复位至 30s",
          M._heal[M.target_key(t)]["backoff"] == tunnel_kit.DEFAULTS["backoff_start_s"],
          M._heal[M.target_key(t)]["backoff"])
    # （10-01 复审补）：600 封顶分支（480→600 后不再增长）
    M.start_target = failing_start
    hh = M._heal[M.target_key(t)]
    hh["backoff"] = 480.0
    hh["streak"] = tunnel_kit.DEFAULTS["confirm_n"]
    hh["next_retry"] = 0.0
    M.ensure_target_healed(t)
    b1 = M._heal[M.target_key(t)]["backoff"]
    hh = M._heal[M.target_key(t)]
    hh["streak"] = tunnel_kit.DEFAULTS["confirm_n"]
    hh["next_retry"] = 0.0
    M.ensure_target_healed(t)
    b2 = M._heal[M.target_key(t)]["backoff"]
    check("退避 600 封顶（480→600→600）",
          b1 == tunnel_kit.DEFAULTS["backoff_max_s"] and b2 == b1, (b1, b2))
finally:
    M.start_target = orig_start

# ---- ④ 密码型：不自动重连（弹窗红线） ----
pw_t = {"name": "pw", "user": "u", "host": "127.0.0.1", "port": 1, "remote_port": 1,
        "key": "", "enabled": True}
M._token_status[M.target_key(pw_t)] = False
calls["n"] = 0
try:
    M._heal.pop(M.target_key(pw_t), None)
    for _ in range(5):
        M.ensure_target_healed(pw_t)
    check("密码型确认死后仍不自动重连", calls["n"] == 0, calls)
finally:
    M.start_target = orig_start

# ---- ⑤ （09-29）：模板 0.1.2 probe 异常 fail-open（蓝本对齐） ----
tt = tunnel_kit.TunnelTarget(
    {"host": "u@h", "remote_port": 1, "local_port": 1},
    probe=lambda: (_ for _ in ()).throw(RuntimeError("probe broken")),
    spawn=lambda args: (_ for _ in ()).throw(AssertionError("never spawn")),
    matches=lambda cmdline: True)   # ADOPTED 腿：让 tasklist 扫描必命中（Windows 进程表非空）
tt.state = tunnel_kit.STATE_OWNED
check("probe 异常时 OWNED 态 fail-open（不判死）", tt.alive() is True)
tt.state = tunnel_kit.STATE_ADOPTED
check("probe 异常时 ADOPTED 态 fail-open", tt.alive() is True)
tt.state = tunnel_kit.STATE_NONE
check("probe 异常时 NONE 态仍 False（无链路可保）", tt.alive() is False)
hdr = [ln for ln in open("src/template/tunnel_kit/tunnel_kit.py", encoding="utf-8").read().splitlines()[:3]
       if "TEMPLATE-VER" in ln]
check("副本头 VER=0.1.2（头变换 TEMPLATE-FROM）", bool(hdr) and "0.1.2" in hdr[0] and "TEMPLATE-FROM" in hdr[0], hdr)

print("TUNNEL HEAL TEST " + ("FAILED: " + ",".join(FAILS) if FAILS else "OK"), flush=True)
sys.exit(1 if FAILS else 0)
