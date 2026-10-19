# -*- coding: utf-8 -*-
"""i18n 字面键存在性。

**为什么需要**：`i18n.t("<缺键>")` **返回键名本身、不抛异常**（实测），而构建的
i18n 门禁只查 9 个核心键 ⇒ "漏加一个键"会**静默**把 `quit_confirm_title` 这样的
键名当文案显示给用户，且门禁全绿。本判据把这一类从"不可见"变成"红"。

**判据**：扫 `src/**/*.py` 里所有 `i18n.t("字面键")`，每个键必须 ∈ en 且 ∈ zh。

**判别力自校（缺了它，"0 缺失"没有意义——匹配器太宽或扫描面为空都会给出 0）**：
  ① **非空**：扫描面必须真的扫到键（否则是"没扫到"而不是"没有"）；
  ② **已知会红**：把一个合成键喂给同一函数，必须被抓到；
  ③ **负对照**：真实键必须不被抓。
三条都过，才允许把"真实扫描 0 缺失"当结论。
"""
import ast
import json
import re
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
LOCALES = Path(__file__).resolve().parents[1] / "locales"
FAILS = []


def check(name, ok, detail=""):
    print(("  ok  " if ok else "  FAIL") + " " + name + ("  " + detail if detail else ""),
          flush=True)
    if not ok:
        FAILS.append(name)


T_KEY = re.compile(r"\bt\(\s*[\"']([^\"']+)[\"']\s*\)")


def literal_keys(root: Path):
    """扫 root 下所有 .py，返回 {键: 首个出现位置}。"""
    found = {}
    for py in sorted(root.rglob("*.py")):
        if "__pycache__" in py.parts:
            continue
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                    and node.func.attr == "t" and node.args \
                    and isinstance(node.args[0], ast.Constant) \
                    and isinstance(node.args[0].value, str):
                found.setdefault(node.args[0].value,
                                 "%s:%d" % (py.relative_to(root.parent).as_posix(), node.lineno))
    return found


def missing(keys, en, zh):
    return sorted(k for k in keys if k not in en or k not in zh)


en = json.loads((LOCALES / "en.json").read_text(encoding="utf-8"))
zh = json.loads((LOCALES / "zh.json").read_text(encoding="utf-8"))
keys = literal_keys(SRC)

# ---- ① 非空（拒绝空真）----
check("scan surface is non-empty (a empty surface would fake a pass)", len(keys) > 50,
      "keys=%d" % len(keys))

# ---- ② 已知会红：合成的缺键必须被抓到 ----
_probe = {"__nonexistent_key_for_control__": "probe"}
check("known-bad control is caught by the same rule",
      missing(_probe, en, zh) == ["__nonexistent_key_for_control__"],
      repr(missing(_probe, en, zh)))

# ---- ③ 负对照 + 真实扫描 ----
sample = sorted(keys)[0]
check("known-good control is NOT caught", missing({sample: ""}, en, zh) == [], sample)

bad = missing(keys, en, zh)
for k in bad:
    print("      MISSING KEY %s   (%s)" % (k, keys[k]))
check("every i18n.t() literal key exists in BOTH tables", not bad,
      "missing=%s" % (bad or "none"))

# ---- 两张表的键集合应当一致（缺一边也是漏翻）----
only_en = sorted(set(en) - set(zh))
only_zh = sorted(set(zh) - set(en))
check("en/zh key sets are identical", not only_en and not only_zh,
      "only_en=%s only_zh=%s" % (only_en[:5], only_zh[:5]))

# ---- 中文值里的中英文空格门禁（用户可见的菜单/对话框/气泡文案）----------------
# 规则：**汉字与拉丁字母/英文词之间必须有一个半角空格**。
#   正例 "启动全部 ssh 隧道"；反例 "启动全部ssh 隧道"——用户在菜单里直接看到。
# 不适用：URL / 命令 / 代码 / 路径 / 格式占位符（%s 等）原样保留；数字+中文单位
# 不强制（本门禁只匹配拉丁字母，天然不涉及数字）。
# 白名单：仅允许"格式占位符 / 命令片段"这类**确需贴写**的例外。本仓当前 0 个例外
# ——加一条白名单就等于放行一类文案，宁可先让门禁红，也不要静默放宽。
SPACING_EXEMPT = ()          # 以后若出现确需贴写的命令片段，在这里列明 pattern
CJK_LATIN = re.compile(r"[\u4e00-\u9fff][A-Za-z]|[A-Za-z][\u4e00-\u9fff]")


def spacing_hits(value):
    """返回中文值与拉丁字母**直接相邻**（无空格）的片段列表。"""
    return [match.group(0) for match in CJK_LATIN.finditer(value)]


def spacing_violations(table, exempt=SPACING_EXEMPT):
    """扫整张词表 → {键: [命中片段]}；白名单 pattern 先剔除再判断。"""
    bad = {}
    for key, value in table.items():
        if not isinstance(value, str):
            continue
        text = value
        for pattern in exempt:
            text = pattern.sub("", text)
        hits = spacing_hits(text)
        if hits:
            bad[key] = hits
    return bad


# 判别力自校（缺了它，"0 命中"证明不了门禁有效）：
check("spacing gate: scan surface is non-empty", len(zh) > 100, "zh values=%d" % len(zh))
check("spacing gate: known-bad control is caught",
      spacing_hits("启动全部ssh 隧道") == ["部s"],
      str(spacing_hits("启动全部ssh 隧道")))
check("spacing gate: known-good control is NOT caught",
      spacing_hits("启动全部 ssh 隧道") == [],
      str(spacing_hits("启动全部 ssh 隧道")))

bad_spacing = spacing_violations(zh)
for key, hits in sorted(bad_spacing.items()):
    print("      SPACING %s -> %s" % (key, hits))
check("zh values: no CJK<->Latin adjacency (one half-width space required)",
      not bad_spacing, "violations=%s" % (bad_spacing or "none"))

# 语言切换项在两种界面语言下都同时显示「English / 中文」——这是刻意的双语对照，
# 也是 en 表里唯一允许出现汉字的键；除此之外 en 表必须全英文。
BILINGUAL_KEYS = {"menu_language"}
zh_chars_in_en = sorted(k for k, v in en.items()
                        if isinstance(v, str) and k not in BILINGUAL_KEYS
                        and re.search(r"[\u4e00-\u9fff]", v))
check("en values contain no Chinese text (except the bilingual language toggle)",
      not zh_chars_in_en, str(zh_chars_in_en))

print("I18N KEYS TEST " + ("FAILED: " + ",".join(FAILS) if FAILS else "OK"), flush=True)
sys.exit(1 if FAILS else 0)
