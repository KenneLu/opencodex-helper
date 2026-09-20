# -*- coding: utf-8 -*-
"""D8 / REVIEW #6: `kill_target_procs` 的作用域 = OWNED 句柄，禁止签名扫场。

缺陷形态（修复前）：函数在 terminate 掉 `_tunnel_procs` 的句柄之后，还按
`cmdline` 特征（`<remote_port>:127.0.0.1:<local_port>` + `user@host`）用
`psutil.process_iter` 扫全场，命中即 terminate。**外部手动另起的同形隧道也满足
该签名**，于是被一起杀掉 —— 违反 G4.2 条款 3「禁止全量签名击杀」与条款 1
（helper 之外的业务自由：不阻止、不清理）。

两条腿，缺一不成立：
  A **正腿**：OWNED 句柄必须被 terminate、登记项必须被 pop（否则"不杀外部"
    可以被"干脆什么都不杀"骗过 —— 那是另一个方向的故障：自己的隧道停不掉）。
  B **负腿（本条的靶）**：停止路径**不得枚举进程表**。签名匹配无法区分
    "我们起的"与"别人起的"，唯一可靠的所有权是本进程持有的 Popen 句柄；
    故断言 `main.py` 的源码里不再出现进程枚举算子。带自证：扫描面非空，
    且一个已知坏的样本会被同一扫描判红（否则"零命中"可能是空真，§D8 第 6 条）。

不 spawn 任何真实进程；数据根隔离（F11/D12）。
"""
import os
import sys
from pathlib import Path
from _cleanup import rmtree_cleanup, scratch_dir  # noqa: E402

_TMP = scratch_dir("ocx-kill-scope-")
os.environ["OPENCODEX_HELPER_DATA_DIR"] = _TMP

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))
import main as M  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(("  ok  " if ok else "  FAIL") + " " + name + ("  " + detail if detail else ""),
          flush=True)
    if not ok:
        FAILS.append(name)


T = {"name": "scope-target", "host": "203.0.113.9", "user": "scope",
     "port": 22, "remote_port": 19999, "enabled": True}


class _FakePopen:
    def __init__(self):
        self.pid = 424242
        self.terminated = False

    def terminate(self):
        self.terminated = True


# --- A 正腿：OWNED 句柄必须被终止、登记项必须被 pop ---
owned = _FakePopen()
M._tunnel_procs[M.target_key(T)] = owned
M.kill_target_procs(T)
check("A: an OWNED handle IS terminated", owned.terminated)
check("A: the OWNED registry entry is popped", M.target_key(T) not in M._tunnel_procs)
check("A: kill is a no-op (no raise) when there is no OWNED handle",
      M.kill_target_procs(T) is None)

# --- B 负腿：停止路径不得枚举进程表（签名扫场已被删）---
src = (SRC / "main.py").read_text(encoding="utf-8")
FORBIDDEN = ("process_iter", "psutil.process", "name.startswith(\"ssh\")", "'plink' in name")


def scan(text):
    return [tok for tok in FORBIDDEN if tok in text]


check("B: scan surface is non-empty (the probe can actually see the forbidden forms)",
      scan("x = psutil.process_iter(['pid'])") == ["process_iter", "psutil.process"])
check("B: no process-table enumeration remains in main.py", scan(src) == [], repr(scan(src)))

# --- 负控：真正的"外部同形隧道"不在 _tunnel_procs 里 ⇒ 该函数看不到它 ---
external = _FakePopen()
external.pid = 31337
M.kill_target_procs(T)     # _tunnel_procs 此刻为空（A 已 pop）
check("B: an external process (never registered as OWNED) is untouched",
      not external.terminated)

check("temp dir cleaned up (no %TEMP% leak)", rmtree_cleanup(_TMP), str(_TMP))
print("OCX KILL-SCOPE TEST " + ("OK" if not FAILS else ("FAILED: " + repr(FAILS))))
sys.exit(1 if FAILS else 0)
