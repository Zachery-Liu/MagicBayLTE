# MagicBayLTE

让 Lenovo Magic Bay LTE 在 Intel macOS 上成为可用的移动网络备用连接，并通过原生菜单栏应用查看状态。

> 社区适配项目。当前仅在一台 Intel 黑苹果、macOS 15.8.1 和 USB `17ef:7240` 模块上完成硬件验证；不承诺其他设备可用。构建最低目标为 macOS 13，13/14 尚未实机验证，Apple Silicon 尚不支持。

没有绑定某一台电脑、模块序列号或 SIM 身份。`17ef:7240` 是该型号共同的 USB VID/PID，接口布局也针对该型号适配；其他 Intel 机器配同型号模块可尝试复用，其他型号需要另行适配。

## 功能

- 原生菜单栏蜂窝信号图标，未就绪时显示斜杠。
- 模块、SIM、运营商、LTE 注册、数据连接、信号强度及本次传输量。
- 信号约 30 秒刷新一次，也可手动检测。
- Wi-Fi / 有线网络不可用后启用 LTE；物理网络恢复且验证通过后结束 LTE 数据会话。
- 平时只查询模块状态，不建立 LTE 数据会话；返回 Wi-Fi 后关闭旧 LTE 接口，避免旧连接继续消耗 LTE 流量。
- 首次安装需要管理员授权，日常启用 / 关闭通过受限本地助手完成，无需重复密码。
- 数据接口标记为按流量计费；具体应用是否遵守取决于应用自身。

## 安装

从 [Releases](https://github.com/Zachery-Liu/MagicBayLTE/releases) 下载 `MagicBayLTE-1.4.0-macOS-Intel.pkg` 和对应的 `SHA256SUMS.txt`。

1. 确认是 Intel Mac，模块 USB ID 为 `17ef:7240`，SIM 已开通流量。
2. 当前版本的后台依赖 Apple 命令行工具提供的 `/usr/bin/python3`（Python 3.9+）。未安装时运行 `xcode-select --install` 并完成安装。
3. 退出正在运行的旧菜单栏应用，再双击安装包，一次授权安装应用和后台助手。更新会短暂停止旧 LTE 服务，正在使用 LTE 时请先恢复其他网络。
4. 从“应用程序”打开 **Magic Bay LTE**。全新安装默认关闭 LTE，请在面板中主动启用；更新保留原来的启用选择。
5. 如需开机显示图标，在右上角“…”中打开“登录时显示图标”。后台服务与菜单栏图标分别管理，退出界面不会停用已启用的 LTE。

当前发行包没有 Developer ID 签名和 Apple 公证，系统可能提示开发者身份未验证。请先核对来源和 SHA-256，再按 macOS 的“隐私与安全性”流程允许打开；不要关闭 Gatekeeper。安装包本身不会自动下载或安装依赖。

安装路径：

- `/Applications/Magic Bay LTE.app`：菜单栏应用。
- `/Library/Application Support/MagicBayLTE/`：root 所有的后台程序、状态和本地日志。
- `/Library/LaunchDaemons/local.magicbay.lte.auto.plist`：后台助手。
- 后台目录的 `Source/`：本安装包对应的完整源码与第三方源码。

卸载请先在菜单中关闭 LTE、关闭“登录时显示图标”并退出应用，再运行：

```sh
sudo /usr/bin/python3 '/Library/Application Support/MagicBayLTE/uninstall.py'
```

卸载保留本地日志与源码，便于排查；不会修改 Wi-Fi 或代理配置。

## 工作方式和限制

应用通过 libusb / MBIM 与模块通信，使用临时 `utun` 数据接口和 SystemConfiguration 网络状态。它不注册原生“蜂窝”设置面板；待命时也没有 LTE IP 接口。常规状态从菜单栏应用查看。

自动接管有故障确认和模块建连过程，需要数秒，现有连接可能需要重建。当前只实现 IPv4 数据通路。Wi-Fi / 有线健康检查会向 AliDNS 和 Cloudflare 发起固定 HTTPS DNS 查询，成功一个即可；恢复后还会按系统当前代理验证普通应用路径。模块信号查询不访问互联网。

Clash / TUN 的行为依赖其路由配置。本项目读取系统代理及可用的本地 Clash 状态来判断兼容性，不修改 Clash 配置。流量统计来自本次程序数据通路的 IP 字节计数，与运营商账单可能不同；不读取套餐余额、短信、手机号、IMEI 或 ICCID。

“…”中的运营商页面指向 Lenovo Connect 的原配卡入口，是否可激活 / 充值取决于 SIM 和运营商。它不是自动读取出的专属账户链接。

## 开发

见 [构建说明](docs/BUILD.md)、[架构与权限](docs/ARCHITECTURE.md)、[发布说明](docs/RELEASING.md)。构建和离线测试不启动 LTE、不关闭 Wi-Fi、不改系统路由。

## 许可证

项目原创代码采用 **AGPL-3.0-only**，见 [LICENSE](LICENSE)。第三方 MIT / LGPL 代码保留原许可证，详见 [NOTICE](NOTICE)。发行包包含完整对应源码和重建脚本，允许修改后重新构建及安装。
