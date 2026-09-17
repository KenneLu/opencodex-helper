# opencodex 助手（opencodex-helper）v1.1.0

Windows 托盘工具：把**多台 VM 的 127.0.0.1:10100** 转发到**本机 opencodex（127.0.0.1:10100）**。VM 里的 cc-switch 无需改配置即可使用 Windows 上的 opencodex。支持多目标、密钥/密码两种认证、令牌扫描与一键生成。

1.1.0 起的补充能力：**在线更新**（菜单「检查助手更新 / 下载并更新助手」，启动时自动检查，zip + sha256 校验，退出托盘后自动完成替换并重启）；**数据区**迁至 `%LOCALAPPDATA%\opencodex-helper\`（旧 exe 旁配置自动迁移，日志 1MB×3 滚动）；**单实例**守护（重复启动弹提示并退出）。

## 运行

双击 `out\opencodex-helper-pkg-<YYYYMMDD-HHmmssfff>\opencodex-helper-1.0.exe`，右下角出现托盘图标。

### 菜单

| 菜单项 | 说明 |
|---|---|
| 隧道状态: 已连接 (n/m) | 启用的目标中已连接数 / 启用数 |
| 穿透目标 ▸ | 每个目标一行：`☑/☐ 名称 IP ●/○ 🔑/🚫/?`<br>☑=启用，●=已连接，🔑=有令牌，🚫=无令牌，?=不可达/未知<br>点击行 = 切换启用（启用即启动隧道，停用即停止） |
| ＋ 添加目标… | 弹窗填写名称/用户名/主机/端口/密钥路径 |
| ✎ 编辑目标… | 选择目标后修改 |
| － 删除目标… | 选择目标后确认删除 |
| 🔑 生成 SSH 令牌… | 选择目标 → 二次确认 → 生成 ed25519 密钥并部署公钥到目标（需密码一次） |
| ↻ 重新扫描令牌 | 重新检测各目标是否有可用密钥 |
| 启动全部 / 停止全部 | 批量操作 |
| 状态刷新间隔 | 20秒 / 1分钟 / 5分钟 / 10分钟 / 30分钟 / 1小时，写回 config.json |
| 开机自启 | 固定菜单名称，当前状态使用 `√` 勾选标记；注册表 HKCU Run（用户级） |
| opencodex 服务: 在线/离线 | 只读状态行，每 5 秒自动刷新 |
| 重启安全 | 只读状态行：已保护 / 有风险 / 原生路由 / 不可用 |
| 打开 opencodex 面板 | 浏览器打开 dashboard |
| 启动 / 停止 / 重启 opencodex 服务 | 直接调用 `ocx start / stop / restart`，结果以通知展示 |
| 打开 opencodex 目录 | 打开 opencodex 数据目录（默认 ~/.opencodex） |
| 打开助手日志目录 | 打开本工具自己的日志目录 |
| 退出 | 停止所有隧道并退出 |

图标颜色：**启用的目标至少一个已连接 → 绿；全断/无启用 → 灰**。主动操作后立即刷新；轮询被动发现状态切换会弹 Windows 通知。

## 认证方式

- **密钥（推荐）**：优先使用本机 `~/.ssh` 默认密钥，或目标配置里指定的 `key` 路径。启动时自动扫描每个目标是否有可用令牌。
- **密码（无令牌时）**：内置 plink（PuTTY 0.85）作为隧道引擎。启动/部署需要密码时弹窗输入，密码**仅内存缓存**，不写盘。
- **一键生成令牌**：`ssh-keygen` 生成 ed25519 密钥（无口令），并把公钥自动追加到目标的 `~/.ssh/authorized_keys`（需目标密码一次），之后免密。

## 配置（config.json）

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

- 每个目标：`name` 显示名，`user` 用户名，`host` 主机/IP（user 留空则直接用 host 作为 ssh 目标，兼容别名），`port` SSH 端口，`key` 私钥路径（留空=默认 ~/.ssh），`remote_port` 该 VM 上监听的端口（cc-switch 指向它），`enabled` 是否启用
- `ocx_cmd`：opencodex CLI 路径，留空自动探测（config 覆盖 > 当前 npm prefix > H:\Tools\npm > 旧 %APPDATA%\npm > PATH）
- `opencodex_home`：opencodex 数据目录，留空用 `OPENCODEX_HOME` 环境变量，再留空用 `~/.opencodex`
- 凭据绝不写进代码/config；密钥只存**路径引用**，密码不落盘

## 打包 / 更新

源码结构：`main.py`、`config.json`、`build.bat`、`README.md`、`bin/plink.exe`（内置密码引擎）、`out/`（发布目录，含 `opencodex-helper-pkg-*`）。

更新流程：改 `main.py` → 运行 `build.bat nopause`（PyInstaller 打包 → 按 `opencodex-helper-pkg-YYYYMMDD-HHmmssfff` 生成扁平新包 → 冒烟测试）→ 启动最新 `opencodex-helper-pkg-*` 目录中的 exe。版本号固定为 `1.0`。

日志：`out\opencodex-helper-pkg-<YYYYMMDD-HHmmssfff>\log\opencodex-helper.log`。所有菜单操作、ocx 命令、隧道启停与状态变化都会写日志。

## 常见问题

- **钥匙显示 🚫**：该目标没有可用 SSH 密钥（可达但认证失败）。可点"生成 SSH 令牌…"一键配置，或手动把本机公钥加到目标 `~/.ssh/authorized_keys`。
- **钥匙显示 ?**：目标不可达（VM 关机/网络不通），无法判断令牌状态。
- **菜单里的 🔑/🚫 显示为方块**：Windows 托盘菜单对 emoji 支持有限，属正常；功能不受影响。
- **启动隧道需要密码**：无令牌时会弹密码框，密码仅本次会话内存缓存，退出后需重新输入。
- **plink 首次连接**：会自动接受并缓存目标 host key（注册表），不会卡住。
- **opencodex 服务无法启动**：看通知里的错误尾部；再打开 opencodex 目录检查日志，或手动运行 `ocx doctor`。
- **官方托盘如何启动**：当前工具使用服务启停/状态/目录菜单；如需官方托盘，命令行执行 `ocx tray start`。
