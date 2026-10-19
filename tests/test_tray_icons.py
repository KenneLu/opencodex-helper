# -*- coding: utf-8 -*-
"""tray_icons 静态贴图断言 + 图标状态四态映射真值表（含负控）。

状态集 = {ok, ok_tunnel, down, down_tunnel} + default 兜底；四态 = 服务健康 ×
任一启用隧道连通，映射纯函数是 `src/main.py` 的 `_tray_state_key`。
实例隔离：import main 之前重定向数据根，绝不碰用户真实 AppData。

断言三层：
  ① 资产层：状态键集 == 资产目录状态集、全套帧在位、按档加载、缺图回退、set_state 去重；
  ② 映射层：真值表四条 + 两条负控（漏隧道维度的错误映射必须被拒、第 4 态不得折叠成 down）；
  ③ 静态层：唯一写入点（`set_state(` 仅 1 处）、无旧状态键、`_menu_signature` 仍含
     `_ocx_state`（防回退：服务健康变化必须触发菜单与图标重画）。
"""
import os
import sys
from pathlib import Path

from _cleanup import rmtree_cleanup, scratch_dir  # noqa: E402

_TMP = scratch_dir("ocx-tray-icons-test-")
os.environ["OPENCODEX_HELPER_DATA_DIR"] = _TMP

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from template.tray_icons import tray_icons  # noqa: E402
from template.appconfig import ICON_STATE_ARTISTS  # noqa: E402
from template.icons.icons import STATE_SIZES  # noqa: E402
import main as M  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(("  ok  " if ok else "  FAIL") + " " + name + ("  " + str(detail) if not ok else ""), flush=True)
    if not ok:
        FAILS.append(name)


# ---------- ① 资产层：状态定义 == 资产目录 + 帧在位 + 加载回退 ----------
ASSET_DIR = ROOT / "resources" / "icons"
STATES = {"ok", "ok_tunnel", "down", "down_tunnel"}

want = set(ICON_STATE_ARTISTS or {}) | {"default"}
have = {p.name for p in ASSET_DIR.iterdir() if p.is_dir()} if ASSET_DIR.is_dir() else set()
check("状态键集 == 资产目录状态集", want == have,
      "定义=%s 资产=%s 差=%s" % (sorted(want), sorted(have), sorted(want ^ have)))
check("四态键名齐（ok/ok_tunnel/down/down_tunnel）", STATES <= want, sorted(want))

missing = [f"{s}/{z}.png" for s in have for z in STATE_SIZES
           if not (ASSET_DIR / s / f"{z}.png").is_file()]
check("全套帧在位（%d 状态 × %d 档）" % (len(have), len(STATE_SIZES)), not missing, missing[:4])

dirs = tray_icons.init()
check("init 解析到资产目录", any(d == ASSET_DIR for d in dirs), [str(d) for d in dirs])
bad_load = [k for k in sorted(want) if tray_icons.get(k, 32).size != (32, 32)]
check("按档加载四态 + default（32 档）", not bad_load, bad_load)
check("缺图回退 default 永不崩", tray_icons.get("__nope__", 24).size == (24, 24))
check("set_state 去重",
      tray_icons.set_state("down_tunnel") in (True, False) and not tray_icons.set_state("down_tunnel"))

# ---------- ② 映射层：四态真值表 + 负控 ----------
CASES = [((False, False), "down"), ((True, False), "ok"),
         ((True, True), "ok_tunnel"), ((False, True), "down_tunnel")]
wrong = [(pair, M._tray_state_key(*pair), key) for pair, key in CASES
         if M._tray_state_key(*pair) != key]
check("四态映射真值表（4 条）", not wrong, wrong)


def _tunnel_blind(ocx_ok, tunnels):
    """负控：故意漏掉隧道维度的错误映射——真值表必须拒绝它。"""
    return "ok" if ocx_ok else "down"


check("负控：漏隧道维度的映射被真值表拒绝",
      not all(_tunnel_blind(*pair) == key for pair, key in CASES))
check("负控：第 4 态（服务断+隧道在）不折叠成 down", M._tray_state_key(False, True) != "down")

# ---------- ③ 静态层：唯一写入点 / 无旧键 / 菜单签名链路 ----------
SRC = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
check("唯一写入点：set_state( 仅 1 处", SRC.count("set_state(") == 1, SRC.count("set_state("))
check("rebuild_menu 用 _tray_state_key 映射", "set_state(_tray_state_key(" in SRC)
check("初始化与运行期同一函数（_tray_state_key 定义 + 2 调用）",
      SRC.count("_tray_state_key(") >= 3, SRC.count("_tray_state_key("))
sig_start = SRC.find("def _menu_signature(")
sig_end = SRC.find("def rebuild_menu(", sig_start)
check("_menu_signature 仍含 _ocx_state（服务健康变化触发重画）",
      sig_start >= 0 and sig_end > sig_start and "_ocx_state" in SRC[sig_start:sig_end])
check('无旧状态键残留（"connected"/"disconnected" 字面量）',
      '"connected"' not in SRC and '"disconnected"' not in SRC)

check("temp dir cleaned up (no %TEMP% leak)", rmtree_cleanup(_TMP), str(_TMP))

print("TRAY ICONS TEST " + ("FAILED: " + ",".join(FAILS) if FAILS else "OK"), flush=True)
sys.exit(1 if FAILS else 0)
