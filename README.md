# opencodex-helper (opencodex 助手) v1.2.1

**English** | [简体中文](README.zh-CN.md)

Windows tray tool that forwards **port 10100 on multiple VMs** to **local opencodex (127.0.0.1:10100)**, so cc-switch inside any VM can use the opencodex on Windows without config changes. Supports multiple targets, key/password auth, token scanning, and one-click token generation.

Unreleased (not yet versioned — dev work lands as local commits; the version changes only at release time):

- **Bilingual UI (T1)**: the tray menu, notifications, dialogs (add/edit/remove target, password prompt, token generation), status lines and service/error messages now go through the family `modules/i18n` module, with `locales/zh.json` as the base table and `locales/en.json` falling back to Chinese for missing keys. A **"Language / 语言"** item in the preferences section toggles between the two; the choice is saved to `config.json` (`language`, default `auto` = follow the Windows UI language) and the menu is rebuilt immediately. Data such as target names/hosts, ports and the opencodex service name is intentionally not translated.
- **Autostart (G4.1)**: the inline registry code was replaced by the family template module `modules/autostart`. Packaged builds point the Run key at the stable install location (`%LOCALAPPDATA%\opencodex-helper\app\opencodex-helper.exe`) when it exists, and fall back to the current exe otherwise. On every start `migrate_autostart()` repairs a Run key whose exe has disappeared — verified live here: the key pointed at the deleted `out\...\opencodex-helper-pkg-20260822-164631246\opencodex-helper-1.0.exe`, and the first start of the fixed build rewrote it to the existing release path. When no Run value exists, the call is a strict no-op: the tool never creates an autostart entry by itself.

Added in 1.1.0: **online updates** (menu "Check for updates / Download and update", auto-checked at startup, zip + sha256 verified, applied after tray quit); **user data area** moved to `%LOCALAPPDATA%\opencodex-helper\` (old exe-side config migrates automatically; logs rotate 1 MB × 3); **single-instance** guard (a second launch shows a notice and exits).

## Running

Launch `release\opencodex-helper-<version>\opencodex-helper.exe`; a tray icon appears in the notification area.

### Menu

| Menu item | Description |
|---|---|
| (info header) | Helper version · tunnel status `connected (n/m)` · opencodex service online/offline · restart safety — read-only lines, grouped at the top since 1.1.0 |
| Check for updates | Queries GitHub Releases and notifies on the result |
| Download and update | Downloads the new version (sha256 verified); applied after you quit the tray |
| Open opencodex panel | Opens the dashboard in a browser (also the double-click default action) |
| Start all / Stop all tunnels | Batch operations |
| Targets ▸ | One row per target: `☑/☐ name IP ●/○ 🔑/🚫/?`<br>☑=enabled, ●=connected, 🔑=has token, 🚫=no token, ?=unreachable/unknown<br>Click a row to toggle it (enabling starts the tunnel, disabling stops it) |
| ＋ Add target… | Dialog for name / user / host / port / key path |
| ✎ Edit target… | Pick a target, then edit |
| － Remove target… | Pick a target, then confirm |
| 🔑 Generate SSH token… | Pick target → confirm → generate an ed25519 key and deploy the public key to the target (needs the password once) |
| ↻ Rescan tokens | Re-check each target for a usable key |
| Start / Stop / Restart opencodex service | Calls `ocx start / stop / restart`; results shown as notifications |
| Open opencodex folder | Opens the opencodex data directory (default ~/.opencodex) |
| Open helper log folder | Opens this helper's own log directory |
| Autostart | Registry `HKCU\...\Run\opencodex-helper` (per-user, no admin); checked = the key exists, and a key pointing at a deleted exe is repaired on the next start |
| Status refresh interval | 20 s / 1 min / 5 min / 10 min / 30 min / 1 h, written back to config.json |
| Language / 语言 | Switches the whole UI between Chinese and English; saved to `config.json` and applied immediately (menu rebuilt) |
| Quit | Asks for confirmation; stopping the tunnels is a persisted checkbox (default off) |

Icon color: **green when at least one enabled target is connected; grey otherwise**. Refreshed immediately after manual actions; passive state flips found by polling raise a Windows notification.

## Authentication

- **Key (recommended)**: uses the local `~/.ssh` default key or the `key` path configured per target. Token availability is scanned automatically at startup.
- **Password (when no token)**: bundled plink (PuTTY 0.85) acts as the tunnel engine. When a password is needed it is asked in a dialog and **cached in memory only** — never written to disk.
- **One-click token generation**: `ssh-keygen` creates an ed25519 key (no passphrase) and appends the public key to the target's `~/.ssh/authorized_keys` (needs the password once); passwordless afterwards.

## Configuration (config.json)

```json
{
  "targets": [
    { "name": "Ubuntu24.04", "user": "xzy_admin", "host": "192.168.190.128",
      "port": 22, "key": "", "remote_port": 10100, "enabled": true }
  ],
  "local_port": 10100,
  "probe_interval_sec": 600,
  "ssh_connect_timeout_sec": 6,
  "probe_timeout_sec": 4,
  "dashboard_url": "http://127.0.0.1:10100",
  "ocx_cmd": "",
  "opencodex_home": "",
  "language": "auto"
}
```

`language` is `auto` (follow the Windows UI language), `zh` or `en`; the "Language / 语言" menu item writes it.

- Per target: `name` display name, `user` username, `host` host/IP (empty user uses host directly as the ssh destination, aliases welcome), `port` SSH port, `key` private-key path (empty = default ~/.ssh), `remote_port` the port listening on that VM (cc-switch points at it), `enabled` toggle.
- `ocx_cmd`: opencodex CLI path; empty auto-probes (config override > current npm prefix > H:\Tools\npm > legacy %APPDATA%\npm > PATH).
- `opencodex_home`: opencodex data directory; empty uses the `OPENCODEX_HOME` env var, then `~/.opencodex`.
- Credentials never live in code or config; keys are stored as **path references** and passwords never touch disk.

## Packaging / Updates

Source layout: `src/main.py`, `src/modules/` (family template modules: appconfig, autostart, log_kit, paths, tray_kit, update_helper), `build.bat`, `README.md` / `README.zh-CN.md`, `bin/plink.exe` (bundled password engine), `.github/workflows/` (CI).

Releases are built by CI: push a `v<semver>` tag (e.g. `v1.2.1`) and the release workflow publishes a zip + sha256 on GitHub Releases — the same layout the in-app updater consumes. The version lives in one place (`VERSION` in main.py); the shipped exe is named `opencodex-helper.exe` without a version.

Local build: `build.bat nopause` (compile gate → PyInstaller → frozen smoke), packages under `release\opencodex-helper-<version>\`. Logs: `%LOCALAPPDATA%\opencodex-helper\log\opencodex-helper.log` (rotating, 1 MB × 3) — menu actions, ocx commands, tunnel up/down, and state changes are all logged.

## Not yet enabled / known gaps

Documented per §I-10 (declare untriggered capabilities and their reasons):

- **Stable install location (§G4.1-1) — not solved, only routed**: `paths.INSTALL_EXE` (`%LOCALAPPDATA%\opencodex-helper\app\`) is defined and autostart prefers it, but nothing installs a build there yet (the updater still replaces the package in place). On a machine without that folder — the normal case today — `get_autostart_cmd()` falls back to the **versioned** `release\opencodex-helper-<version>\` path (that is what the live Run key holds after the 1.2.2 self-heal), so renaming or deleting that folder strands the key again until the next start repairs it. Full G4.1-1 (updater installs into the stable folder) remains open.
- **Bounded cleanup (§G4.2-3) — known violation, not fixed this round**: `kill_target_procs()` (main.py ~238-256) still kills *every* ssh/plink process whose command line matches the target, and it is reached from `start_target` / `stop_target` / `on_delete_target` / `on_stop_all`. A tunnel the user started by hand for the same target can therefore be killed. Fixing it means restructuring tunnel ownership/lifecycle, which needs manual regression, so it is deliberately left for a separate change (see REVIEW.md finding #6).
- **Tunnel adoption (§G4.2-2/4)**: there is no ADOPTED/OWNED ownership model; "running" is derived from a health probe each poll rather than from a registered handle.
- **i18n coverage (§T1) — implemented, with a named residual**: the module is adopted and `--lang-audit` reports 0 Chinese literals outside the zh table in `src/main.py`, so every menu item, notification, dialog, status line and service/error message in this tool is translated. Residual: the audit only scans `src/main.py`; text produced by other files (e.g. `tray_kit`'s built-in dialog wording when no override is passed, Python/Tk exception strings) is not covered. Anything not routed through `i18n.t()` falls back to Chinese — tracked here rather than silently claimed as done.
- **Settings window (§T3)**: everything is edited through tray submenus and Tk dialogs (targets, keys, password prompt); there is no single settings window despite 9 config keys.
- **`release.bat`**: does not exist. `tests/` does, as of 2026-09-19 - `tests/test_*.py` covers the single-instance guard, the real startup path, the i18n menu refresh, the update chain, UI marshalling and the quit fail-open path, and `build.bat` runs **every** one of them as a gate, so the frozen `--smoke` is no longer the only business check.
- **`service_link` (§G4.2 reference state machine)**: the template ships `modules/service_link`; this tool does not adopt it.
- **Quit-path fail-open (§G4.1-4 / T7) - interim local form, template absorption pending**: when the dialog chain is unavailable (`Tk()` raises `TclError`, e.g. a hollowed `_internal/`), `on_quit` logs one line and quits with `quit_stop_tunnels=False` instead of silently refusing to exit. It is deliberately a local three-way decision inside `on_quit`; the obligation is to call `tray_kit`'s unified form once it ships (see CHANGELOG `## Unreleased`).

## FAQ

- **Token shows 🚫**: no usable SSH key for that target (reachable but auth failed). Use "Generate SSH token…" or add your public key to the target's `~/.ssh/authorized_keys` manually.
- **Token shows ?**: target unreachable (VM off / network down); token state unknown.
- **🔑/🚫 render as boxes**: the Windows tray menu has limited emoji support — cosmetic only.
- **Starting a tunnel asks for a password**: no token yet; the password dialog caches in memory for this session only.
- **plink first connection**: the host key is accepted and cached in the registry automatically; it will not hang.
- **opencodex service won't start**: check the tail of the error in the notification, open the opencodex folder for logs, or run `ocx doctor`.
- **Where is the official tray**: this tool covers service start/stop/status and the data directory; for the official tray run `ocx tray start`.
