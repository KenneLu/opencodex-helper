# -*- coding: utf-8 -*-
"""托盘创建失败可读化：PermissionError → MessageBoxW 可读提示 + 崩溃日志 + 退出码 2。

回归背景（1.2.4 用户实测）：从受限终端/沙箱启动 exe 时，`TRAY_ICON.run()` 在建托盘
窗口处抛 PermissionError（`ChangeWindowMessageFilterEx` 拒绝访问）。旧代码让它一路冒到
`__main__`，冻结的 noconsole 程序把英文 traceback 弹给用户、并且没有任何可照做的说明。

1.2.5 起两条入口（都在 `src/main.py`，模板仓不动）：
  * `run_tray(icon, setup)`：`icon.run()` 抛异常 → 可读提示 + best-effort 崩溃日志 + 返回 2；
  * `main_entry()`：启动期其它未捕获异常 → 同样的可读提示 + 返回 2（不再裸抛）。
提示文案全部走 i18n 词表（中英双语），含「受限终端/沙箱」「从资源管理器双击」
「重启资源管理器」这些可照做的动作，并附 traceback 尾部供维护者定位。

断言（mock MessageBox，不起真托盘、不占生产互斥体）：
  ① 文案齐备且带维护者详情；② run_tray 失败 → 2 + 一次弹窗 + 崩溃日志落盘；
  ③ run_tray 成功 → 0 + 无弹窗（负控）；④ main_entry 未捕获异常 → 2 + 可读弹窗；
  ⑤ 无头入口（--smoke）只写日志不弹窗（负控，避免挂死构建）。
"""
import os
import sys
from pathlib import Path

from _cleanup import rmtree_cleanup, scratch_dir  # noqa: E402

_TMP = scratch_dir("ocx-tray-failure-test-")
os.environ["OPENCODEX_HELPER_DATA_DIR"] = _TMP
os.environ["OPENCODEX_HELPER_CONFIG"] = str(Path(_TMP) / "config.json")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import main as M  # noqa: E402
from template.paths import LOG_DIR, USER_DATA_DIR  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(("  ok  " if ok else "  FAIL") + " " + name + ("  " + str(detail) if not ok else ""),
          flush=True)
    if not ok:
        FAILS.append(name)


# MessageBox 全部拦下来：测试不弹真窗口，同时作为"用户看到什么"的记录器。
MESSAGES = []
M._message_box = lambda text, title=None: MESSAGES.append((text, title)) or True

CRASH_LOG = Path(LOG_DIR) / "startup-error.log"
if CRASH_LOG.exists():
    CRASH_LOG.unlink()


class _BoomIcon:
    """模拟受限环境：建托盘窗口时拒绝访问。"""

    def run(self, setup=None):
        raise PermissionError(13, "Access is denied")


class _OkIcon:
    """模拟正常：消息循环跑完就返回（测试里不需要真的循环）。"""

    def run(self, setup=None):
        return None


# ---- ① 文案：可照做的动作 + 维护者详情 ------------------------------------
_DETAIL = ("Traceback (most recent call last):\n"
           "  File \"<frozen>\", line 1, in run\n"
           "PermissionError: [WinError 5] Access is denied")
text = M._tray_failure_text(PermissionError(13, "Access is denied"), _DETAIL)
required = ["tray_failed_headline", "tray_failed_reason", "tray_failed_hint_explorer",
            "tray_failed_hint_restart", "failure_detail_hint"]
missing = [k for k in required if M.i18n.t(k) not in text]
check("tray failure text carries every actionable hint", not missing, missing)
check("tray failure text keeps a traceback tail for the maintainer",
      "PermissionError" in text and _DETAIL[-80:] in text)
check("tray failure text leads with the readable headline (not a raw english traceback)",
      text.startswith(M.i18n.t("tray_failed_headline")))

# ---- ② run_tray：失败 → 退出码 2 + 一次可读弹窗 + 崩溃日志 ----------------
MESSAGES.clear()
rc = M.run_tray(_BoomIcon(), setup=None)
check("run_tray converts a tray PermissionError into exit code 2", rc == 2, rc)
check("run_tray shows exactly one readable MessageBox with the failure title",
      len(MESSAGES) == 1 and MESSAGES[0][1] == M.i18n.t("startup_failure_title"),
      repr(MESSAGES))
check("the MessageBox body is the readable hint text, not an english-only traceback",
      bool(MESSAGES) and M.i18n.t("tray_failed_headline") in MESSAGES[0][0],
      (MESSAGES[0][0][:120] if MESSAGES else ""))
check("run_tray writes the crash log best-effort",
      CRASH_LOG.is_file() and M.i18n.t("tray_failed_headline") in CRASH_LOG.read_text(
          encoding="utf-8", errors="replace"),
      str(CRASH_LOG))
check("run_tray never raises (the caller gets an exit code, not a traceback)", True)

# ---- ③ 负控：正常结束 → 0，不弹窗 -----------------------------------------
MESSAGES.clear()
_log_before = CRASH_LOG.read_text(encoding="utf-8", errors="replace")
rc = M.run_tray(_OkIcon(), setup=None)
check("run_tray returns 0 when the tray loop ends normally", rc == 0, rc)
check("negative control: success path shows no failure dialog", not MESSAGES, repr(MESSAGES))
check("negative control: success path writes no new crash log",
      CRASH_LOG.read_text(encoding="utf-8", errors="replace") == _log_before)

# ---- ④ main_entry：其它启动期异常 → 2 + 可读弹窗 --------------------------
MESSAGES.clear()
_real_main = M.main


def _boom_main():
    raise PermissionError(13, "simulated startup failure")


M.main = _boom_main
try:
    rc = M.main_entry()
finally:
    M.main = _real_main
check("main_entry turns an unexpected startup exception into exit code 2", rc == 2, rc)
check("main_entry shows one readable dialog", len(MESSAGES) == 1, repr(MESSAGES))
_headline_prefix = M.i18n.t("startup_failed_headline", "").rstrip()
check("main_entry dialog names the actual exception",
      bool(MESSAGES)
      and MESSAGES[0][0].startswith(_headline_prefix)
      and "simulated startup failure" in MESSAGES[0][0],
      (MESSAGES[0][0][:120] if MESSAGES else ""))
check("main_entry dialog carries the traceback tail for the maintainer",
      "Traceback" in (MESSAGES[0][0] if MESSAGES else ""))

# ---- ⑤ 负控：无头入口（--smoke）不弹窗，但日志照写 ------------------------
MESSAGES.clear()
CRASH_LOG.unlink()          # 从干净状态验证"写了"
_argv = sys.argv
sys.argv = [_argv[0], "--smoke"]
try:
    M._show_startup_failure("headless probe text")
finally:
    sys.argv = _argv
check("negative control: headless (--smoke) shows no dialog", not MESSAGES, repr(MESSAGES))
check("headless still writes the best-effort crash log",
      CRASH_LOG.is_file() and "headless probe text" in CRASH_LOG.read_text(
          encoding="utf-8", errors="replace"), str(CRASH_LOG))

check("crash log stays inside the isolated user data root",
      str(USER_DATA_DIR) in str(CRASH_LOG), str(CRASH_LOG))
check("temp dir cleaned up (no %TEMP% leak)", rmtree_cleanup(_TMP), str(_TMP))
print("TRAY FAILURE TEST " + ("FAILED: " + ",".join(FAILS) if FAILS else "OK"), flush=True)
sys.exit(1 if FAILS else 0)
