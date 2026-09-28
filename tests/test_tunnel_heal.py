# -*- coding: utf-8 -*-
"""W7 隧道自愈语义（Decision 10）：N=3 确认 / 退避门 / 密码型不自动重连。

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


# ---- ① Decision 10 命令行段（密钥型隧道长连接） ----
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

print("TUNNEL HEAL TEST " + ("FAILED: " + ",".join(FAILS) if FAILS else "OK"), flush=True)
sys.exit(1 if FAILS else 0)
