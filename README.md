# opencodex-helper (opencodex 助手) v1.1.0

**English** | [简体中文](README.zh-CN.md)

Windows tray tool that forwards **port 10100 on multiple VMs** to **local opencodex (127.0.0.1:10100)**, so cc-switch inside any VM can use the opencodex on Windows without config changes. Supports multiple targets, key/password auth, token scanning, and one-click token generation.

Added in 1.1.0: **online updates** (menu "Check for updates / Download and update", auto-checked at startup, zip + sha256 verified, applied after tray quit); **user data area** moved to `%LOCALAPPDATA%\opencodex-helper\` (old exe-side config migrates automatically; logs rotate 1 MB × 3); **single-instance** guard (a second launch shows a notice and exits).

## Running

Launch `out\opencodex-helper-pkg-<YYYYMMDD-HHmmssfff>\opencodex-helper.exe`; a tray icon appears in the notification area.

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
| Autostart | Registry HKCU Run (per-user); state shown with a `√` checkmark |
| Status refresh interval | 20 s / 1 min / 5 min / 10 min / 30 min / 1 h, written back to config.json |
| Quit | Stops all tunnels and exits |

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
  "opencodex_home": ""
}
```

- Per target: `name` display name, `user` username, `host` host/IP (empty user uses host directly as the ssh destination, aliases welcome), `port` SSH port, `key` private-key path (empty = default ~/.ssh), `remote_port` the port listening on that VM (cc-switch points at it), `enabled` toggle.
- `ocx_cmd`: opencodex CLI path; empty auto-probes (config override > current npm prefix > H:\Tools\npm > legacy %APPDATA%\npm > PATH).
- `opencodex_home`: opencodex data directory; empty uses the `OPENCODEX_HOME` env var, then `~/.opencodex`.
- Credentials never live in code or config; keys are stored as **path references** and passwords never touch disk.

## Packaging / Updates

Source layout: `main.py`, `update_helper.py`, `build.bat`, `README.md` / `README.zh-CN.md`, `bin/plink.exe` (bundled password engine), `.github/workflows/` (CI).

Releases are built by CI: push a `v<semver>` tag (e.g. `v1.1.0`) and the release workflow publishes a zip + sha256 on GitHub Releases — the same layout the in-app updater consumes. The version lives in one place (`VERSION` in main.py); the shipped exe is named `opencodex-helper.exe` without a version.

Local build: `build.bat nopause` (compile gate → PyInstaller → smoke check), packages under `out\opencodex-helper-pkg-*`.

Logs: `%LOCALAPPDATA%\opencodex-helper\log\opencodex-helper.log` (rotating, 1 MB × 3). Menu actions, ocx commands, tunnel up/down, and state changes are all logged.

## FAQ

- **Token shows 🚫**: no usable SSH key for that target (reachable but auth failed). Use "Generate SSH token…" or add your public key to the target's `~/.ssh/authorized_keys` manually.
- **Token shows ?**: target unreachable (VM off / network down); token state unknown.
- **🔑/🚫 render as boxes**: the Windows tray menu has limited emoji support — cosmetic only.
- **Starting a tunnel asks for a password**: no token yet; the password dialog caches in memory for this session only.
- **plink first connection**: the host key is accepted and cached in the registry automatically; it will not hang.
- **opencodex service won't start**: check the tail of the error in the notification, open the opencodex folder for logs, or run `ocx doctor`.
- **Where is the official tray**: this tool covers service start/stop/status and the data directory; for the official tray run `ocx tray start`.
