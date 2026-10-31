# 架构与权限

`MenuBarLTE/` 是普通用户的 AppKit / SwiftUI 应用。它只读 root 后台导出的 JSON 状态，通过本地 Unix socket 发送固定的启用 / 关闭命令。后台使用 `getpeereid` 核对当前控制台用户，不接受任意命令、路径或 shell 字符串。

`lte_helper.py` 由系统 LaunchDaemon 以 root 运行，保存启用选择并管理 `lte_auto.py`。`lte_auto.py` 结合物理接口可用性、HTTPS 探测与切换策略管理 MBIM 引擎。模块的 USB 访问、临时 utun、接口计费标记及网络状态发布需要管理员权限。可执行代码安装在 root 所有且普通用户不可写的目录。

物理网络正常时只运行 control-only monitor，读取 SIM / 运营商 / 信号，并确认 session 0 已停用。无物理网络后才创建数据会话。返回物理网络时，先进入“切换中”，停止实际数据会话与接口，再验证新的出口，最后显示就绪。不能只改 UI 或把网络服务降为 Scoped，否则旧连接仍可能沿 LTE 传输。

`network_watch.c` 只读监听 SystemConfiguration 变化以唤醒检查。事件机制不可用时回退定时检查。`failover_policy.py` 设置故障 / 恢复确认窗口以抑制抖动。模块状态每 30 秒查询一次，手动信号按钮也复用现有控制会话，不额外抢占 USB。

不会主动关闭 Wi-Fi、重启网络服务、修改代理 / Clash / TUN 配置或发起自动断网测试。启用 LTE 表示允许在物理网络经检查不可用时自动使用移动流量。

本地日志及状态可能包含模块提供的运营商、IP 地址、时间等信息；它们不上传，且不属于公开仓库内容。提交问题前请自行删去个人数据，不要上传整个运行目录。
