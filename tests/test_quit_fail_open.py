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
# ---------------------------------------------------------------------------
# ⑤ 模板件契约（消费侧）：`confirm_quit_dialog` 的**取消路径必须返回 dict，不是 None**
#
# tray_kit 2.2.1 把契约收紧成"取消 = {'go': False}，永不 None"。而本仓
# `_decide_quit()` 里的 `if choice is None:` 是 **fail-open 落点**：一旦有人照旧
# docstring 把它"修好"成"取消返回 None"，用户点取消就会被读成"链路不可用" ⇒
# 直接退出 —— 那正是 #44-A 的缺陷原形。所以从**消费侧**把契约钉死。
#
# 用**假 Tk** 把真函数推到取消分支：不建任何窗口、不碰桌面。真实 Tk 里
# `wait_window()` 阻塞到窗口被销毁，而"取消"就是"销毁但不改 result"；这里在
# wait_window 里按下取消按钮，等价于用户点「取消」/ 按 Esc。
# **正对照**（点「确定」）必须在同一次运行里成立，否则"永远返回 go=False 的假实现"
# 也能让取消那条腿通过。
# ---------------------------------------------------------------------------
_PRESS = {}


class _FakeWidget:
    """只实现 confirm_quit_dialog 用到的表面；窗口方法一律 no-op。"""

    def __init__(self, *_a, **_k):
        self.destroyed = False
        self._hooks = {}

    def winfo_screenwidth(self):
        return 1920

    def winfo_screenheight(self):
        return 1080

    def winfo_width(self):
        return 380

    def winfo_height(self):
        return 160

    def protocol(self, name, fn):
        if name == "WM_DELETE_WINDOW":
            self._hooks["close"] = fn

    def bind(self, seq, fn):
        if "Escape" in seq:
            self._hooks["escape"] = fn

    def wait_window(self):
        # 用户按下某个按钮 —— 真实 Tk 里 cancel()/confirm() 都在按钮的 command 里
        _PRESS[_PRESS["which"]]()

    def destroy(self):
        self.destroyed = True

    def __getattr__(self, _name):
        def _noop(*_a, **_k):
            return None
        return _noop


def _install_fake_tk(which):
    """which: 'cancel' | 'confirm'。把 tkinter 换成只够跑完这个函数的替身。"""
    _PRESS.clear()
    _PRESS["which"] = which
    _PRESS["cancel"] = lambda: None

    mod = types.ModuleType("tkinter")
    mod.Tk = _FakeWidget
    mod.Toplevel = lambda *_a, **_k: _FakeWidget()

    class _BoolVar:
        def __init__(self, master=None, value=False):
            self._v = value

        def get(self):
            return self._v

    mod.BooleanVar = _BoolVar
    mod.Frame = _FakeWidget
    mod.Label = _FakeWidget
    mod.Checkbutton = _FakeWidget

    def _button(_master=None, **kw):
        # 按**文案**区分两个按钮，不依赖内部创建顺序（顺序是实现细节）
        if kw.get("text") == "NO":
            _PRESS["cancel"] = kw.get("command")
        elif kw.get("text") == "YES":
            _PRESS["confirm"] = kw.get("command")
        return _FakeWidget()

    mod.Button = _button
    saved = sys.modules.get("tkinter")
    sys.modules["tkinter"] = mod
    return saved


def _restore_tk(saved):
    if saved is None:
        sys.modules.pop("tkinter", None)
    else:
        sys.modules["tkinter"] = saved


def _run_dialog(which):
    saved = _install_fake_tk(which)
    try:
        return M.tray_kit.confirm_quit_dialog(
            "probe-app", None, False, None, None,
            title="t", body_text="b", confirm_text="YES", cancel_text="NO")
    finally:
        _restore_tk(saved)


logs.clear()
_r_cancel = _run_dialog("cancel")
check("widget contract: CANCEL returns a dict, not None (fail-open arm stays reachable)",
      _r_cancel is not None, "returned %r" % (_r_cancel,))
check("widget contract: cancel is expressed as go=False, not as a missing return",
      isinstance(_r_cancel, dict) and _r_cancel.get("go") is False,
      "returned %r" % (_r_cancel,))
_r_confirm = _run_dialog("confirm")
check("control: CONFIRM still yields go=True (so the cancel leg is discriminating)",
      isinstance(_r_confirm, dict) and _r_confirm.get("go") is True,
      "returned %r" % (_r_confirm,))


check("temp dir cleaned up (no %TEMP% leak)", rmtree_cleanup(_TMP), str(_TMP))
print("QUIT FAIL-OPEN TEST " + ("FAILED: " + ",".join(FAILS) if FAILS else "OK"), flush=True)
sys.exit(1 if FAILS else 0)
