# -*- coding: utf-8 -*-
"""#45 ①：口令型目标冷启动时，"我起不来"不得先杀掉在用的隧道。

缺陷形态（修复前 `start_target` 的语句顺序）：

    if probe_target(t):      # 探测为假
        ... return
    kill_target_procs(t)     # ← 先杀
    ...
    if tok is False and not pw:      # 再问口令
        pw = ask_password(t)
        if not pw:                   # 用户在口令框上取消
            return ...               # ← 我们一条隧道都没起，但已经杀过了

即 **清理陈旧隧道排在"确定要启动"之前**。本机今天不触发的唯一原因是"密钥可用
⇒ probe 为真 ⇒ 上面就早退了"；口令型目标冷启动必然走到这里。

两条腿，缺一条都不成立：

  A  **修复的靶**：tok=False + 无缓存口令 + 用户在口令框取消
     ⇒ `kill_target_procs` **一次都不许被调**。
     反向格（构造"实例正从目标目录跑"，见本仓其他测试）在这里不适用：
     本条的靶是**不该发生的动作**，所以用"记录调用"的方式断言，而不是看后果。
  B  **退化对照**：确凿阴性 + 凭据可用 ⇒ 陈旧隧道**仍然要清理**。
     没有 B，"不许杀"可以被"把 kill 删掉"骗过 —— 那是另一个方向的故障
     （死隧道永远清不掉）。

实例隔离（F11/D12）：import main 之前重定向数据根。
本文件不 spawn 任何真实进程：probe / Popen / sleep / 口令输入全为替身。
"""
import os
import sys
import types
from pathlib import Path
from _cleanup import rmtree_cleanup, scratch_dir  # noqa: E402

_TMP = scratch_dir("ocx-start-failopen-")
os.environ["OPENCODEX_HELPER_DATA_DIR"] = _TMP

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import main as M  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(("  ok  " if ok else "  FAIL") + " " + name + ("  " + detail if detail else ""),
          flush=True)
    if not ok:
        FAILS.append(name)


# 注入一个真目标：没有它，"零次调用"会因为 targets 为空而恒真（无对照的断言）。
T = {"name": "probe-target", "host": "127.0.0.1", "port": 22,
     "remote_port": 10100, "enabled": True}
KEY = M.target_key(T)

_saved = (M.kill_target_procs, M.probe_target, M.ask_password,
          M.ensure_plink_hostkey, M.subprocess, M.time)
killed = []


def _setup(probe_result, tok):
    killed.clear()
    M.kill_target_procs = lambda t: killed.append(t)
    M.probe_target = lambda t: probe_result
    M.ask_password = lambda t: None                 # 用户在口令框上按取消
    M.ensure_plink_hostkey = lambda t, pw: None
    M.subprocess = types.SimpleNamespace(
        Popen=lambda *a, **k: types.SimpleNamespace(terminate=lambda: None), DEVNULL=-3)
    M.time = types.SimpleNamespace(sleep=lambda _s: None)
    M._token_status = {KEY: tok}
    M._pw_cache = {}
    M._state = {}
    M._tunnel_procs = {}


try:
    # ---- A：口令型冷启动 + 用户取消口令 ⇒ 不许杀 ----
    _setup(probe_result=False, tok=False)
    M.start_target(T)
    check("A: password prompt cancelled -> NOTHING is killed", killed == [],
          "killed=%r" % (killed,))

    # ---- A2：同上但口令拿到了 ⇒ 这时才允许清理（证明 A 不是"永不杀"的退化） ----
    _setup(probe_result=False, tok=False)
    M.ask_password = lambda t: "hunter2"
    M.start_target(T)
    check("A2: once credentials ARE obtained, cleanup happens as before",
          killed == [T], "killed=%r" % (killed,))

    # ---- B：确凿阴性 + 凭据可用 ⇒ 陈旧隧道仍须清理 ----
    _setup(probe_result=False, tok=True)
    M.start_target(T)
    check("B: confident negative with a usable key still cleans up", killed == [T],
          "killed=%r" % (killed,))

    # ---- C：探测为真（已连接）⇒ 早退，不杀不问 ----
    _setup(probe_result=True, tok=True)
    rc = M.start_target(T)
    check("C: already-connected short-circuit kills nothing", killed == [],
          "killed=%r rc=%r" % (killed, rc))
finally:
    (M.kill_target_procs, M.probe_target, M.ask_password,
     M.ensure_plink_hostkey, M.subprocess, M.time) = _saved

check("temp dir cleaned up (no %TEMP% leak)", rmtree_cleanup(_TMP), str(_TMP))
print("START TARGET FAIL-OPEN TEST "
      + ("FAILED: " + ",".join(FAILS) if FAILS else "OK"), flush=True)
sys.exit(1 if FAILS else 0)
