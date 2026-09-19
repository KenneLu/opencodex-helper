# Changelog

All notable changes to opencodex-helper are documented here.
The tagging convention matches the versions in this file.

## Unreleased

Version number is intentionally NOT bumped: as of 2026-09-19 the owner ruled
that dev work lands as local commits only and the version changes only when a
release is cut (STANDARDS "发版节奏" clause 7). The 1.2.2 bump made earlier in
this batch was rolled back to 1.2.1.

- **`APP_DIR` now has exactly one source** (`paths.APP_DIR`). `main.py` used to derive
  its own copy - right when frozen (the exe dir) but `src/` in dev, where `paths` says
  the repo root. The two only had to agree in the packaged build, so the split stayed
  invisible: in dev `PLINK_PATH` resolved to `src/bin/plink.exe`, which does not exist,
  while every gate stayed green. The local definition is gone and `APP_DIR` is imported
  from `modules.paths` with the rest of the paths; `bin/` lives at the repo root, which
  is also what `--add-data` bundles.
- Tests: `test_startup_path.py` pins both halves of the `APP_DIR` fix - it is the same
  object as `modules.paths.APP_DIR`, and `plink.exe` really is a file in dev mode.
- Template resync: `modules/update_helper` -> 1.4.2 (1.4.1 made `:stage_invalid` preserve
  the scene like `:install_failed`; 1.4.2 guards the third `start` - the one after a
  restore - because "the restore did not error" is not "the exe is back"). `.py` and
  `README.md` copied; the `.py` header re-stamped with the new TEMPLATE-VER.

- Update housekeeping is now actually wired in (T4 收尾): `sweep_stale_update_dirs()`
  runs at startup and removes `<APP_ID>-update-*` staging dirs that an interrupted
  updater left in %TEMP% (only those older than 1 h, so an in-flight update is never
  touched - ~50 MB per run otherwise accumulates forever); `pop_failed_update_note(
  UPDATE_DIR)` then consumes the failed-update marker **once** and, when it was set,
  the tray raises `notify_update_failed_prev` from its `setup` callback once the icon
  is visible. Both were dead template code before (0 call sites in `src/*.py`). The
  string the module returns is Chinese, so only its truthiness is used and the
  user-visible sentence comes from the locale table (T1); the detail is already in
  `update.log`. `--smoke` returns before `main()`, so the probe stays read-only (D3-03).
- `icon.run()` now passes a `setup` callback (sets `visible = True` explicitly, which
  pystray skips when a custom setup is given) - that is the hook the housekeeping
  notification rides on.
- Tests: `test_startup_path.py` now covers all three acceptance points - the **real**
  sweep deletes an aged dir while keeping a fresh one and an unrelated one (with
  `tempfile.tempdir` redirected to a throwaway root), the **real** marker is reported
  once and is silently gone on a second start, and `main()` calls sweep-then-note and
  surfaces the i18n message.
- Template resync: `modules/tray_kit` -> 2.2.0 - `mutex_name_ok()` is now the single
  shape predicate shared by the guard, the probe and `single_instance_free()`; the
  guard passes an illegal name **through** with a log line instead of failing closed
  (D3.2), leaving the "go red" job to the build-time probe (D3.3). Call sites unchanged;
  the module `README.md` was resynced byte-for-byte as well.

- Updates (T4): the update path no longer reads `update_helper`'s mutable
  globals. The discovered version is cached in `LATEST_VERSION` (from
  `check_update()`'s return value), `download_and_prepare()`'s returned script
  path is stored in `PENDING_UPDATE_CMD`, the "Download and update" item is
  enabled from that cache, and the quit path launches the stored script. The
  template package's `import *` had copied `PENDING_CMD` (so `apply.cmd` was
  never launched) and `UPDATE_READY` was never assigned (item grey forever);
  keying off return values instead makes this tool independent of that state
  (verified: `grep update_helper.(PENDING_CMD|UPDATE_READY)` is empty).
  Also resynced `modules/update_helper` to template 1.3.0.
- Tests (D1 1.4/1.5): added `tests/` with four suites, all isolated (each pins
  its own `OPENCODEX_HELPER_DATA_DIR` before importing main; no mutex, no
  registry, no network) and wired into build.bat as a gate:
  - `test_single_instance.py` - mutex name matches the family derivation, the
    kernel accepts it, the old illegal name still fails, acquire/refuse uses a
    test-only name (SINGLE-08), and the guard fails open.
  - `test_startup_path.py` - runs the real `main()` with heavy stubs and asserts
    the startup sequence is reached (log `starting`, `migrate_autostart`, the
    initial token scan and probe).
  - `test_i18n_menu.py` - switching language reads via the package namespace and
    really rebuilds the menu into English (the 2.1.1 regression).
  - `test_update_chain.py` - stubbed update chain: the discovered version is
    cached, the returned apply-script path is stored, and quit launches it.
- Frozen smoke now **dual-pins** `OPENCODEX_HELPER_DATA_DIR` +
  `OPENCODEX_HELPER_CONFIG` (the config is a throwaway copy inside smoke-data,
  so the shipped config is never rewritten) - D1 unified convention.
- Single-instance guard probe (D3.1/C-10): `--smoke` now calls
  `tray_kit.mutex_name_is_valid(APP_ID)`, so an illegal mutex name fails the
  build loudly - that silent failure once kept a sibling tool dead for months
  while every gate stayed green. `tests/test_single_instance.py` asserts the
  probe both ways. Resynced `modules/tray_kit` to 2.1.0, and `build.bat`'s
  VERSION parse switched to the D1 two-step form (a trailing comment can no
  longer leak into the release path).
- i18n / T1 (bilingual UI): adopted the template `modules/i18n` 2.1.1
  (light form) - `locales/zh.json` (base) + `locales/en.json`, flat KV,
  en falls back to zh. Every tray menu label, notification, dialog (add/edit/
  remove target, password, token generation), status line and service/error
  message goes through `i18n.t()`. A "Language / 语言" item sits in the
  preferences section; switching re-inits the language, persists it to
  `config.json` (`language`), and **rebuilds the menu explicitly** - the
  current language is read via `i18n.current_lang()`, not `i18n.LANG`
  (2.1.1 fixed the stale package re-export copy). Data - target names/hosts,
  ports, the opencodex service name - is not translated.
- Build gate: `py_compile` list includes `modules/i18n/i18n.py`; a new gate
  asserts the zh/en tables both answer the core keys (D1-04); a new
  `--lang-audit` gate statically scans `src/main.py` for Chinese literals
  outside the zh table (AST-based, docstrings excluded) - currently
  **0 untranslated**. PyInstaller bundles `locales` via `--add-data`.
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
