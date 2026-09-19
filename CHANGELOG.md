# Changelog

All notable changes to opencodex-helper are documented here.
The tagging convention matches the versions in this file.

## 1.2.2

Patch release (owner ruling, D15: +0.0.1).

- Autostart (G4.1): the inline Run-key code was replaced by the family
  template module `modules/autostart` (T3, 1.1.1, byte-identical copy;
  build.bat's py_compile list covers it). Packaged builds now prefer the
  stable install location (`%LOCALAPPDATA%\opencodex-helper\app\
  opencodex-helper.exe`) when it exists and fall back to the current exe
  otherwise.
- Autostart self-heal (G4.1-3/5), **verified live on this machine**: the Run
  key pointed at the deleted
  `out\opencodex-helper-pkg-20260822-164631246\opencodex-helper-1.0.exe`.
  Starting the frozen 1.2.2 build once (isolated `OPENCODEX_HELPER_DATA_DIR`)
  rewrote it to the existing
  `release\opencodex-helper-1.2.2\opencodex-helper.exe` and logged
  `autostart migrated: <old> -> <new>`. The owner approved keeping the
  repaired value (the dead link was not restored). The smoke path returns
  before the migration, so `--smoke` stays read-only (D3-03); starting with
  no Run value at all is a strict no-op (never creates an entry).
- Template resync: `paths.py` -> 1.1.3, `tray_kit.py` -> 2.0.2 (mechanical;
  call sites unchanged).
- Build gate: `build.bat nopause norun` green -> `SMOKE OK`,
  `release\opencodex-helper-1.2.2\opencodex-helper.exe`.
- Honest limitation: **the full stable-install mechanism (G4.1-1) is still
  not implemented**. With no `...\app\` folder, autostart now points at the
  versioned `release\opencodex-helper-1.2.2\` path (that is exactly what the
  live key holds now), so renaming/deleting that folder strands the key until
  the next start self-heals it. Tracked in the README "known gaps" section.

## 1.2.1

- Internal structure only: family template modules moved under `modules/`
  (imports via `from modules import ...`); sync_check and CI compile lists
  updated. No behavior change.
- Bilingual README (baseline 8): `README.md` is now the English canonical
  version with `README.zh-CN.md` as the Chinese one, language switch lines on
  top of both; stale 1.0-era packaging notes refreshed. Both files now ship
  inside the release zip.

## 1.2.0

- Internal refactor (no behavior change): user-data paths via `paths.py`
  (family template T2), rotating logging via `log_kit.py` (T12), and the
  single-instance guard via `tray_kit.py` (T7) - byte-identical copies of the
  family template modules, verified by the build's sync_check gate.

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
