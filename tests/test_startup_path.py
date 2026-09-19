# -*- coding: utf-8 -*-
"""正常启动路径存活（D3-01 / SINGLE-04）：跑**真正的 main()**，只把重资源换成替身。

回归背景：诊断参数（`--smoke`）曾绕过正常启动路径，于是"冒烟全绿、工具其实打不开"
能长期共存。本测试走 main() 正常分支，断言守卫放行后启动序列真的推进：日志出现
`startup`、`migrate_autostart` 被调用、开局扫描/探测都启动了。

实例隔离（F11/D12）：import main 之前重定向数据根与配置。SSH 探测、本地 HTTP 健康
检查、托盘与监控循环全部打桩——本测试只验证启动骨架，不触网、不占锁。
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="ocx-startup-test-")
os.environ["OPENCODEX_HELPER_DATA_DIR"] = _TMP
os.environ["OPENCODEX_HELPER_CONFIG"] = str(Path(_TMP) / "config.json")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import main as M  # noqa: E402
from modules.paths import LOG_PATH  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(("  ok  " if ok else "  FAIL") + " " + name + ("  " + detail if detail else ""),
          flush=True)
    if not ok:
        FAILS.append(name)


CALLS = {"autostart": 0, "scans": 0, "probes": 0, "monitors": 0}


class _Icon:
    def __init__(self, *a, **k):
        self.menu = k.get("menu")

    def run(self, setup=None):
        if setup:
            setup(self)

    def stop(self):
        pass

    def update_menu(self):
        pass

    def notify(self, *a, **k):
        pass


def _started(key):
    def _run(*_a, **_k):
        CALLS[key] += 1
    return _run


M.tray_kit.acquire_single_instance = lambda *_a, **_k: True
M.tray_kit.warn_duplicate_instance = lambda *_a, **_k: None
M.pystray.Icon = _Icon
M.autostart.migrate_autostart = lambda **k: CALLS.__setitem__("autostart", CALLS["autostart"] + 1)
M.scan_all_tokens = _started("scans")
M.initial_probe_all = _started("probes")
M.monitor_loop = _started("monitors")
M.ocx_monitor_loop = _started("monitors")
M.ocx_health = lambda: {"ok": False, "port": None, "safety": None}
M.update_helper.check_update = lambda version, force=False: {"newer": False, "latest": "", "current": version}

rc = M.main()

text = LOG_PATH.read_text(encoding="utf-8", errors="replace") if LOG_PATH.exists() else ""
check("main() returned 0 (guard passed)", rc == 0, "rc=%r" % (rc,))
check("startup sequence reached (log has startup)",
      any("starting" in line for line in text.splitlines()), repr(text.splitlines()[:2]))
check("migrate_autostart called on startup", CALLS["autostart"] == 1, repr(CALLS))
check("initial token scan and probe started",
      CALLS["scans"] == 1 and CALLS["probes"] == 1, repr(CALLS))
check("log written inside the isolated data dir", str(LOG_PATH).startswith(_TMP),
      str(LOG_PATH))

shutil.rmtree(_TMP, ignore_errors=True)
print("STARTUP PATH TEST " + ("FAILED: " + ",".join(FAILS) if FAILS else "OK"), flush=True)
sys.exit(1 if FAILS else 0)
