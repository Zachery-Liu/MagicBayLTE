# Magic Bay LTE

Magic Bay LTE 是一款适用于 Intel macOS 的 Lenovo Magic Bay LTE 菜单栏工具，用于查看蜂窝网络状态，并在 Wi-Fi 或有线网络不可用时提供 LTE 备用连接。

## 免责声明 | Disclaimer

### 中文

本项目是由社区独立开发和维护的非官方开源项目，旨在为 Lenovo Magic Bay LTE 设备提供 macOS 平台下的兼容性支持。

本项目与联想（Lenovo）及苹果（Apple）不存在任何隶属、合作、赞助或官方认可关系，亦非上述公司的官方产品或驱动程序。

Lenovo、Magic Bay、Apple 及 macOS 等名称和商标归其各自权利人所有。本项目提及上述名称仅用于说明设备兼容性及运行平台，不代表任何官方授权、认可或关联关系。

### English

This is an independent, community-developed and maintained, unofficial open-source project intended to provide macOS compatibility support for Lenovo Magic Bay LTE devices.

This project is not affiliated with, endorsed by, or sponsored by Lenovo or Apple, and is not an official product or driver of either company.

Lenovo, Magic Bay, Apple, and macOS are trademarks of their respective owners. References to these names are used solely to identify compatible hardware and the target operating system, and do not imply any official authorization, endorsement, or affiliation.

## 功能

- **自动备用联网**：Wi-Fi 或有线网络不可用时使用 LTE，恢复后结束 LTE 数据连接并返回原网络。
- **连接状态**：查看模块接入、SIM 卡、运营商、网络注册和数据连接状态。
- **信号检测**：菜单栏显示蜂窝信号，约每 30 秒更新一次，也可手动检测。
- **流量统计**：查看 LTE 上传、下载流量及实时速度。
- **连接管理**：支持启用、停用、重新连接及模块热插拔。
- **登录启动**：可选择在登录 macOS 时显示菜单栏图标。

## 使用要求

| 项目 | 要求 |
| --- | --- |
| 设备 | Lenovo Magic Bay LTE，USB ID `17ef:7240` |
| 电脑 | Intel / x86_64；暂不支持 Apple Silicon |
| 系统 | 构建最低目标为 macOS 13，已验证系统版本为 macOS 15.8.1；macOS 13/14 的兼容性尚未确认 |
| SIM 卡 | 已开通移动数据服务的 SIM 卡 |
| 运行依赖 | Apple Command Line Tools 提供的 Python 3.9 或更新版本 |

## 安装

1. 从 [Releases](https://github.com/Zachery-Liu/MagicBayLTE/releases) 下载 Intel 版 `.pkg` 安装包。
2. 如果尚未安装 Apple Command Line Tools，在终端运行 `xcode-select --install` 并完成安装。
3. 打开安装包，按提示完成安装。安装需要管理员授权。
4. 从“应用程序”打开 **Magic Bay LTE**，在面板中开启 **启用 LTE**。

当前发行包尚未经过 Apple 公证。首次打开时，如系统提示开发者身份未验证，请核对下载来源，并在“系统设置 → 隐私与安全性”中确认打开。

更新前请退出旧版界面；如果正在使用 LTE 上网，请先连接可用的 Wi-Fi 或有线网络。

## 使用

点击菜单栏中的蜂窝信号图标即可查看状态。首次安装默认停用 LTE；启用后，软件会自动管理备用连接，无需手动切换出口。

- **检测**：立即更新信号强度。
- **… → 重新连接 LTE**：结束现有 LTE 会话并重新初始化连接。
- **… → 运营商服务 ↗**：打开 Lenovo Connect 服务页面。
- **… → 登录时显示图标**：设置菜单栏应用是否随登录启动。

日常启用、停用和重新连接无需重复输入管理员密码。退出菜单栏应用只关闭界面；需要停止 LTE 服务时，请先关闭 **启用 LTE**。

LTE 联网会消耗 SIM 卡流量，软件显示的流量统计仅供参考，以运营商账单为准。网络切换需要一定的检测和建连时间，现有连接可能需要重新建立。当前数据连接支持 IPv4。

## 卸载

关闭 **启用 LTE** 和 **登录时显示图标**，退出应用后，在终端运行：

```sh
sudo /usr/bin/python3 '/Library/Application Support/MagicBayLTE/uninstall.py'
```

卸载后保留本地日志和对应源码。

## 开发文档

[构建说明](docs/BUILD.md) · [项目结构](docs/PROJECT_STRUCTURE.md) · [架构说明](docs/ARCHITECTURE.md) · [发布说明](docs/RELEASING.md)

## 许可证

项目采用 [AGPL-3.0-only](LICENSE)。第三方组件保留各自许可证与版权声明，详见 [NOTICE](NOTICE)。
