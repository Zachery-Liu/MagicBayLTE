# MagicBayLTE 1.4.0 — 首个公开预览版

为 Lenovo Magic Bay LTE (`17ef:7240`) 提供原生 macOS 菜单栏状态与自动备用网络。

- 显示模块、SIM、运营商、注册状态、信号及本次传输量。
- 首次授权安装后台助手后，日常启用 / 关闭无需重复管理员密码。
- Wi-Fi 恢复时真正停用 LTE 数据会话并关闭旧接口，避免旧连接继续消耗流量。
- 平时只查询模块状态；信号每 30 秒刷新，可手动检测。
- 项目采用 AGPL-3.0-only；包内提供完整对应源码及第三方依赖源码。

**要求**：Intel macOS 13+，Apple Command Line Tools 的 Python 3.9+，USB `17ef:7240` 模块。仅在一台 Intel 机器和 macOS 15.8.1 上完成运行逻辑验证，其他机器、macOS 13/14 与新安装流程还需要用户验证，Apple Silicon 暂不支持。全新安装默认关闭 LTE。

**签名状态**：app 为 ad hoc 签名，pkg 未签名、未经过 Apple 公证。请核对 SHA256SUMS 和来源，按系统授权流程打开。

**下载**：Intel `.pkg` 为安装包，`-source.tar.gz` 为对应完整源码，`SHA256SUMS.txt` 为文件校验值。请在有可用 Wi-Fi / 有线网络且退出旧界面后更新，安装时会暂停旧 LTE 服务。
