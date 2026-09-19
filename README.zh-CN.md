# opencodex 助手（opencodex-helper）v1.2.2

[English](README.md) | **简体中文**

Windows 托盘工具：把**多台 VM 的 127.0.0.1:10100** 转发到**本机 opencodex（127.0.0.1:10100）**。VM 里的 cc-switch 无需改配置即可使用 Windows 上的 opencodex。支持多目标、密钥/密码两种认证、令牌扫描与一键生成。

1.2.2 起的补充能力：

- **开机自启（G4.1）**：内联注册表代码改为家族模板件 `modules/autostart`。打包态优先指向稳定安装位（`%LOCALAPPDATA%\opencodex-helper\app\opencodex-helper.exe`，存在时），否则退回当前 exe；每次启动执行 `migrate_autostart()`，把指向"已消失的 exe"的 Run 键静默修回——**本机已实测**：原键指向已被删除的 `out\...\opencodex-helper-pkg-20260822-164631246\opencodex-helper-1.0.exe`，首次启动 1.2.2 后即被改写为存在的 `release\opencodex-helper-1.2.2\opencodex-helper.exe`。若注册表里根本没有这个值，则不会写任何东西——工具绝不自行新增自启项。

1.1.0 起的补充能力：**在线更新**（菜单「检查助手更新 / 下载并更新助手」，启动时自动检查，zip + sha256 校验，退出托盘后自动完成替换并重启）；**数据区**迁至 `%LOCALAPPDATA%\opencodex-helper\`（旧 exe 旁配置自动迁移，日志 1MB×3 滚动）；**单实例**守护（重复启动弹提示并退出）。

## 运行

双击 `release\opencodex-helper-<版本>\opencodex-helper.exe`，右下角出现托盘图标。

### 菜单

| 菜单项 | 说明 |
|---|---|
| （顶部信息区） | 助手版本 · 隧道状态 `已连接 (n/m)` · opencodex 服务在线/离线 · 重启安全——只读行，1.1.0 起统一置顶 |
| 检查助手更新 | 查询 GitHub Releases 并以通知汇报结果 |
| 下载并更新助手 | 下载新版本（sha256 校验），退出托盘后自动替换并重启 |
| 打开 opencodex 面板 | 浏览器打开 dashboard（也是双击托盘的默认动作） |
| 启动全部 / 停止全部隧道 | 批量操作 |
| 穿透目标 ▸ | 每个目标一行：`☑/☐ 名称 IP ●/○ 🔑/🚫/?`<br>☑=启用，●=已连接，🔑=有令牌，🚫=无令牌，?=不可达/未知<br>点击行 = 切换启用（启用即启动隧道，停用即停止） |
| ＋ 添加目标… | 弹窗填写名称/用户名/主机/端口/密钥路径 |
| ✎ 编辑目标… | 选择目标后修改 |
| － 删除目标… | 选择目标后确认删除 |
| 🔑 生成 SSH 令牌… | 选择目标 → 二次确认 → 生成 ed25519 密钥并部署公钥到目标（需密码一次） |
| ↻ 重新扫描令牌 | 重新检测各目标是否有可用密钥 |
| 启动 / 停止 / 重启 opencodex 服务 | 直接调用 `ocx start / stop / restart`，结果以通知展示 |
| 打开 opencodex 目录 | 打开 opencodex 数据目录（默认 ~/.opencodex） |
| 打开助手日志目录 | 打开本工具自己的日志目录 |
| 开机自启 | 注册表 `HKCU\...\Run\opencodex-helper`（用户级，免管理员）；勾选 = 该项存在，指向已删除 exe 的旧键会在下次启动时自愈 |
| 状态刷新间隔 | 20秒 / 1分钟 / 5分钟 / 10分钟 / 30分钟 / 1小时，写回 config.json |
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

源码结构：`src/main.py`、`src/modules/`（家族模板件：appconfig、autostart、log_kit、paths、tray_kit、update_helper）、`build.bat`、`README.md` / `README.zh-CN.md`、`bin/plink.exe`（内置密码引擎）、`.github/workflows/`（CI）。

正式发布走 CI：推送 `v<semver>` tag（如 `v1.2.2`），release workflow 会在 GitHub Releases 发布 zip + sha256——与站内更新器消费的布局一致。版本号单一事实源在 `main.py` 的 `VERSION`；随包 exe 名为不带版本号的 `opencodex-helper.exe`。

本机构建：`build.bat nopause`（编译门禁 → PyInstaller 打包 → 冻结冒烟），产物在 `release\opencodex-helper-<版本>\`。

日志：`%LOCALAPPDATA%\opencodex-helper\log\opencodex-helper.log`（滚动，1MB×3）。所有菜单操作、ocx 命令、隧道启停与状态变化都会写日志。

## 未启用能力 / 已知缺口

按 §I-10 逐条注明未触发能力及原因：

- **稳定安装位（§G4.1-1）—— 只做了"优先指向"，机制本身仍未实现**：`paths.INSTALL_EXE`（`%LOCALAPPDATA%\opencodex-helper\app\`）已定义、自启也优先指向它，但没有任何流程把版本装进稳定位（更新器仍是原地替换当前包）。在"稳定位不存在"的常态下（本机即如此），`get_autostart_cmd()` 退回**带版本号**的 `release\opencodex-helper-<版本>\`——这也是本次自愈后 Run 键实际持有的值；该目录改名/被删仍会断链，靠下次启动自愈兜底。完整 G4.1-1（更新器把版本装进稳定位）仍是待办。
- **有界清理（§G4.2-3）—— 已知违规，本轮未修**：`kill_target_procs()`（main.py 约 238-256 行）仍会按命令行签名击杀**所有**匹配的 ssh/plink 进程，且被 `start_target` / `stop_target` / `on_delete_target` / `on_stop_all` 调用；用户手动为同一目标起的隧道可能被误杀。修复需要重构隧道的所有权/生命周期并做人工回归，故留待单独改动（见 REVIEW.md 发现 #6）。
- **隧道接入（§G4.2-2/4）**：没有 ADOPTED/OWNED 所有权模型，"已连接"由每拍健康探测得出，而非登记后的固定句柄。
- **i18n（§T1）**：仓库已公开，触发条件成立，但没有 `i18n` 模块，界面文案全部中文硬编码。
- **设置窗口（§T3）**：目标、密钥、密码全靠托盘子菜单和 Tk 弹窗编辑；有 9 个配置键却没有统一设置窗口。
- **`tests/` 与 `release.bat`**：两者都缺；唯一的业务检查是 `build.bat` 里的冻结 `--smoke`（D1-05/D3-02）。注意 `import main` 有落盘副作用，补测试前需要先做 T6 harness。
- **`service_link`（§G4.2 参考状态机）**：模板已提供 `modules/service_link`，本工具未采纳。

## 常见问题

- **钥匙显示 🚫**：该目标没有可用 SSH 密钥（可达但认证失败）。可点"生成 SSH 令牌…"一键配置，或手动把本机公钥加到目标 `~/.ssh/authorized_keys`。
- **钥匙显示 ?**：目标不可达（VM 关机/网络不通），无法判断令牌状态。
- **菜单里的 🔑/🚫 显示为方块**：Windows 托盘菜单对 emoji 支持有限，属正常；功能不受影响。
- **启动隧道需要密码**：无令牌时会弹密码框，密码仅本次会话内存缓存，退出后需重新输入。
- **plink 首次连接**：会自动接受并缓存目标 host key（注册表），不会卡住。
- **opencodex 服务无法启动**：看通知里的错误尾部；再打开 opencodex 目录检查日志，或手动运行 `ocx doctor`。
- **官方托盘如何启动**：当前工具使用服务启停/状态/目录菜单；如需官方托盘，命令行执行 `ocx tray start`。
