# Changelog

All notable changes to opencodex-helper are documented here.
The tagging convention matches the versions in this file.

## 1.2.0

- Internal refactor (no behavior change): user-data paths via `paths.py`
  (family template T2), rotating logging via `log_kit.py` (T12), and the
  single-instance guard via `tray_kit.py` (T7) - byte-identical copies of the
  family template modules, verified by the build's sync_check gate.

## Unreleased

- Bilingual README (baseline 8): `README.md` is now the English canonical
  version with `README.zh-CN.md` as the Chinese one, language switch lines on
  top of both; stale 1.0-era packaging notes refreshed. Both files now ship
  inside the release zip.

## 1.1.0

- Online update: "检查助手更新 / 下载并更新助手" tray items backed by GitHub
  Releases (startup auto-check + 24h throttle, zip + sha256 verified, applied
  after tray quit via a one-shot robocopy script that restarts the exe).
- Version consolidated to a single source of truth (`VERSION = "1.1.0"` in
  main.py; the old code/docstring disagreed between 1.0 and 1.2) and switched
  to semver.
- User data moved to `%LOCALAPPDATA%\opencodex-helper\` (config.json + log\);
  the old exe-side config.json is migrated once on first run. The exe
  directory can now be replaced wholesale by the updater.
- Rotating log (1 MB × 3 backups, ~4 MB ceiling) instead of an unbounded file.
- Single-instance mutex: launching a second copy now shows a notice and exits.
- Tray menu restructured to the house standard: all read-only status lines
  (helper version, tunnel status, opencodex health/safety) grouped at the top,
  updates next, "打开 opencodex 面板" as the double-click default action, then
  tunnel/opencodex service controls, targets, open items, preferences, quit.
- Repository baseline: git/CI (tests + tag-triggered release), LICENSE,
  CHANGELOG, .gitignore.

## 1.0

- Initial state: multi-target SSH reverse tunnels, plink fallback auth,
  opencodex service control, token status scanning.
