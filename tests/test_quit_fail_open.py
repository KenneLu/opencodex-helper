# -*- coding: utf-8 -*-
"""退出路径 fail-open 回归（#44 A）。

背景（ocx 1.2.2 实证，2026-09-19 17:00:51 / 17:01:27）：`_internal/` 被 rm -rf 掏空
→ Tk 读不到 init.tcl → `tkinter.Tk()` 抛 TclError → 富对话框与原生 askyesno **双双
不可用**。旧代码把「链路不可用」(None) 与「用户明确取消」({"go": False}) 塞进同一个
`return`，于是点「退出」静默无反应——用户被锁死在工具里，只能用任务管理器。

三条腿，缺一条都不算修好：
  ① 链路不可用 → **必须退出**（icon.stop 真被调用、日志真的是 fail-open 那一行）；
  ② 「不可用 ⇒ 放行」≠「默认同意」：不得停服务（kill_target_procs 不被调用）；
  ③ 用户明确取消 → **必须不退出**（负向对照：防「默认 go=True」把确认框拆了）。

Tk 桩的严格性（J-坑）：桩抛的是**真的 `tkinter.TclError`**（从真 tkinter 取类），
不是长得像的异常——否则生产代码的 `except Exception` 会替我们掩盖类型不符。
桩只在 `Tk()` 上红，导入本身不红（真 tkinter 也是这个语义：导入不开窗口）。

实例隔离（F11/D12）：import main 之前重定向数据根，绝不碰用户真实 AppData。
"""
import os
import sys
import types
from pathlib import Path
from _cleanup import rmtree_cleanup, scratch_dir  # noqa: E402  （R2 位置 + 删前放句柄）

_TMP = scratch_dir("ocx-quit-test-")
os.environ["OPENCODEX_HELPER_DATA_DIR"] = _TMP

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import main as M  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(("  ok  " if ok else "  FAIL") + " " + name + ("  " + detail if detail else ""),
          flush=True)
    if not ok:
        FAILS.append(name)


class _Icon:
    def __init__(self):
        self.notified = []
        self.stopped = False

    def notify(self, message, title=None):
        self.notified.append(str(message))

    def update_menu(self):
        pass

    def stop(self):
        self.stopped = True


# ---------------------------------------------------------------------------
# Tk 桩：复刻 1.2.2 的真实故障——运行时在，init.tcl 读不到，Tk() 必炸。
# ---------------------------------------------------------------------------
import tkinter as _real_tk            # noqa: E402  导入本身不开窗口
import tkinter.messagebox as _real_mb  # noqa: E402

_REAL_TK, _REAL_MB = _real_tk, _real_mb
_REAL_TCL_ERROR = _real_tk.TclError
_TCL_MSG = ("Can't find a usable init.tcl in the following directories: "
            "{C:/.../_internal/_tcl_data} - the first dialog after a hollowed _internal")


def _install_broken_tk():
    mod = types.ModuleType("tkinter")
    mod.TclError = _REAL_TCL_ERROR

    def _Tk(*_a, **_k):
        raise _REAL_TCL_ERROR(_TCL_MSG)

    mb = types.ModuleType("tkinter.messagebox")

    def _askyesno(*_a, **_k):
        raise _REAL_TCL_ERROR(_TCL_MSG)

    mod.Tk = _Tk
    mb.askyesno = _askyesno
    mod.messagebox = mb
    sys.modules["tkinter"] = mod
    sys.modules["tkinter.messagebox"] = mb


def _restore_tk():
    sys.modules["tkinter"] = _REAL_TK
    sys.modules["tkinter.messagebox"] = _REAL_MB


# 日志捕获：断言走的是哪条分支，而不是只看 icon.stopped（后者可能因别的路径为真）
logs = []
_orig_log = M._log
M._log = lambda *parts: logs.append(" ".join(str(p) for p in parts))

_orig_confirm = M.tray_kit.confirm_quit_dialog
_orig_kill = M.kill_target_procs
_orig_post = M.ui_post


def _broken_confirm(*_a, **_k):
    """富对话框：1.2.2 里它自己就要建 Tk 根，同样炸。"""
    raise _REAL_TCL_ERROR(_TCL_MSG)


def _raise_quiet(*_a, **_k):
    raise RuntimeError("Tk runtime missing")


def _leg(fn):
    """跑一条腿，无论如何都还原补丁与 Tk 桩。"""
    icon = _Icon()
    try:
        fn(icon)
    finally:
        M.tray_kit.confirm_quit_dialog = _orig_confirm
        M.kill_target_procs = _orig_kill
        M.ui_post = _orig_post
        _restore_tk()
    return icon


# 注入一个假目标，让「勾选 = 停签名匹配的隧道」这条真的可断言（否则 targets 空，
# 断言会变成恒真——那正是 J-坑说的"桩比实现宽松，把契约冲突藏起来"）。
_PROBE_TARGET = {"name": "probe-target", "host": "127.0.0.1", "port": 22,
                 "remote_port": 10100}
_orig_targets = M.CFG["targets"]

killed = []

# ① 链路不可用 ⇒ 必须退出
logs.clear()
M.CFG["targets"] = [_PROBE_TARGET]
M.tray_kit.confirm_quit_dialog = _broken_confirm
M.kill_target_procs = lambda t: killed.append(t)
_install_broken_tk()
_icon1 = _leg(lambda ic: M.on_quit(ic, None))
check("broken dialog chain still quits (fail open)", _icon1.stopped is True,
      "stopped=%r" % (_icon1.stopped,))
check("the fail-open branch is the one that ran (not some other path)",
      any("quit confirm unavailable" in ln for ln in logs), repr(logs[-3:]))

# ② 放行 ≠ 默认同意：服务不得被停（不勾选 = 不碰签名匹配的隧道）
check("fail open does not stop the service (no signature-wide kill)",
      killed == [], repr(killed))

# ②b 封送本身失败（UI 线程没了）也必须放行
killed.clear()
logs.clear()
M.CFG["targets"] = [_PROBE_TARGET]
M.kill_target_procs = lambda t: killed.append(t)
M.ui_post = _raise_quiet          # UI 线程不可用：ui_post 抛
_icon2 = _leg(lambda ic: M.on_quit(ic, None))
check("marshalling failure also fails open", _icon2.stopped is True,
      "stopped=%r" % (_icon2.stopped,))
check("marshalling failure does not stop the service", killed == [], repr(killed))

# ③ 负向对照：用户明确取消 ⇒ 不退出、也不停服务（确认框没被拆）
killed.clear()
logs.clear()
M.CFG["targets"] = [_PROBE_TARGET]
M.kill_target_procs = lambda t: killed.append(t)
M.tray_kit.confirm_quit_dialog = lambda *a, **k: {"go": False, "stop_service": True}
_icon3 = _leg(lambda ic: M.on_quit(ic, None))
check("explicit cancel still does NOT quit", _icon3.stopped is False,
      "stopped=%r" % (_icon3.stopped,))
check("the cancel branch really ran (dialog answered, not skipped)",
      any("quit cancelled by user" in ln for ln in logs), repr(logs[-3:]))
check("cancel stops nothing even when the box was ticked", killed == [], repr(killed))

# ④ 正常路径没被改坏：用户答「是」且勾选 ⇒ 真退出且真停
killed.clear()
logs.clear()
M.CFG["targets"] = [_PROBE_TARGET]
M.kill_target_procs = lambda t: killed.append(t)
M.tray_kit.confirm_quit_dialog = lambda *a, **k: {"go": True, "stop_service": True}
_icon4 = _leg(lambda ic: M.on_quit(ic, None))
check("a real user 'yes' still quits", _icon4.stopped is True,
      "stopped=%r" % (_icon4.stopped,))
check("a real user 'yes' still honours the 'stop service' checkbox",
      killed == [_PROBE_TARGET], repr(killed))

M.CFG["targets"] = _orig_targets

M._log = _orig_log
check("temp dir cleaned up (no %TEMP% leak)", rmtree_cleanup(_TMP), str(_TMP))
print("QUIT FAIL-OPEN TEST " + ("FAILED: " + ",".join(FAILS) if FAILS else "OK"), flush=True)
sys.exit(1 if FAILS else 0)
