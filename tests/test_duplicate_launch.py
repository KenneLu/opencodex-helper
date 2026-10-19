# -*- coding: utf-8 -*-
"""重复启动优雅化：第二实例写 show.request 静默退出，常驻实例消费后弹托盘气泡。

回归背景（1.2.4 及以前）：`main()` 遇到 `acquire_single_instance() == False` 会调
`tray_kit.warn_duplicate_instance()` 弹**模态 MessageBox**——用户把它当成报错，而且
无人值守的构建会被挂死。1.2.5 起：第二实例把 `show.request` 写进用户数据根（对齐模板
`quit.request` 的请求文件约定）后静默 `return 0`；常驻实例的 `show_watch_loop` 消费它 →
删文件 + `TRAY_ICON.notify` 气泡「已在运行」。

断言（全 mock，不起托盘、不占生产互斥体、不写真实 AppData）：
  ① 无请求时消费是 no-op（负控）；
  ② 第二实例写请求文件；常驻侧消费后文件消失且 notify 文案来自当前语言表；
  ③ 重复消费不再通知（负控）；
  ④ 真正的 `main()` 走重复启动分支：返回 0、写 show.request、**不再**调
     warn_duplicate_instance / MessageBox。
"""
import os
import sys
from pathlib import Path

from _cleanup import rmtree_cleanup, scratch_dir  # noqa: E402

_TMP = scratch_dir("ocx-dup-launch-test-")
os.environ["OPENCODEX_HELPER_DATA_DIR"] = _TMP
os.environ["OPENCODEX_HELPER_CONFIG"] = str(Path(_TMP) / "config.json")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import main as M  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(("  ok  " if ok else "  FAIL") + " " + name + ("  " + str(detail) if not ok else ""),
          flush=True)
    if not ok:
        FAILS.append(name)


class _Icon:
    def __init__(self):
        self.notified = []

    def notify(self, message, title=None):
        self.notified.append((message, title))


check("show.request lives in the user data root (same convention as quit.request)",
      M.SHOW_REQUEST_PATH.name == "show.request"
      and Path(_TMP) in M.SHOW_REQUEST_PATH.parents,
      str(M.SHOW_REQUEST_PATH))

# 常驻实例的图标替身（notify 记录器）。生产里 `_TRAY_ICON` 由 main() 赋值。
M._TRAY_ICON = _Icon()

# ---- ①② 第二实例写请求 → 常驻侧消费并通知 ---------------------------------
check("negative control: consume with no request is a no-op",
      M.consume_show_request() is False and not M._TRAY_ICON.notified,
      repr(M._TRAY_ICON.notified))
check("stale show.request does not exist before the duplicate launch",
      not M.SHOW_REQUEST_PATH.exists(), str(M.SHOW_REQUEST_PATH))

check("duplicate launch writes show.request", M.request_show_notification() is True
      and M.SHOW_REQUEST_PATH.is_file(), str(M.SHOW_REQUEST_PATH))
check("request file records the second instance pid",
      M.SHOW_REQUEST_PATH.read_text(encoding="utf-8").strip().isdigit(),
      M.SHOW_REQUEST_PATH.read_text(encoding="utf-8"))

check("resident instance consumes the request (file deleted)",
      M.consume_show_request() is True and not M.SHOW_REQUEST_PATH.exists())
check("resident instance notifies 'already running' via the tray in the current language",
      M._TRAY_ICON.notified == [(M.i18n.t("notify_already_running"), M.i18n.t("app_name"))],
      repr(M._TRAY_ICON.notified))

# ---- ③ 负控：再消费一次不再通知 -------------------------------------------
_notified_before = list(M._TRAY_ICON.notified)
check("negative control: consuming again notifies nothing",
      M.consume_show_request() is False and M._TRAY_ICON.notified == _notified_before,
      repr(M._TRAY_ICON.notified))

# ---- ④ 真 main() 的重复启动分支：静默 return 0，不弹任何模态框 ------------
WARNED = []
BOXES = []
M.tray_kit.acquire_single_instance = lambda *_a, **_k: False
M.tray_kit.warn_duplicate_instance = lambda *_a, **_k: WARNED.append(True)
M._message_box = lambda text, title=None: BOXES.append((text, title)) or True

if M.SHOW_REQUEST_PATH.exists():
    M.SHOW_REQUEST_PATH.unlink()
rc = M.main()
check("duplicate launch returns 0 silently", rc == 0, rc)
check("duplicate launch wrote show.request (hand-over to the resident instance)",
      M.SHOW_REQUEST_PATH.is_file(), str(M.SHOW_REQUEST_PATH))
check("duplicate launch no longer calls warn_duplicate_instance (no modal)",
      not WARNED, repr(WARNED))
check("duplicate launch pops no MessageBox at all", not BOXES, repr(BOXES))

M._TRAY_ICON.notified.clear()
check("resident side then consumes the hand-over and notifies",
      M.consume_show_request() is True
      and M._TRAY_ICON.notified == [(M.i18n.t("notify_already_running"), M.i18n.t("app_name"))],
      repr(M._TRAY_ICON.notified))

check("temp dir cleaned up (no %TEMP% leak)", rmtree_cleanup(_TMP), str(_TMP))
print("DUPLICATE LAUNCH TEST " + ("FAILED: " + ",".join(FAILS) if FAILS else "OK"), flush=True)
sys.exit(1 if FAILS else 0)
