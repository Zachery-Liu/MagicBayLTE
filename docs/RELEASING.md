# 公开仓库与发行

仓库：`https://github.com/Zachery-Liu/MagicBayLTE`。项目源码已公开；Release 安装包与完整对应源码、校验文件一同分发。

## 生成发行文件

1. 确定版本号，保持 `app/build_app.py` 中的应用版本和 `scripts/package_release.py` 中的安装包版本一致，并更新版本说明。
2. 按 [构建说明](BUILD.md) 完成构建、离线测试、打包和解包验证。`dist/` 中会生成 `.pkg`、`-source.tar.gz` 及 `SHA256SUMS.txt`。
3. 在测试机器或测试启动卷验证安装、更新和卸载。真实 LTE 出口切换需要单独安排测试窗口，构建脚本不执行断网测试。

## GitHub Release

在仓库 Releases 页面创建发行版，选择对应的 `v版本号` 标签，上传上述三个文件并填写版本说明。普通发行版的 **Release label** 选 **None**；预览版选 **Pre-release**，未完成时可保存为 Draft。

已发布版本的安装包、源码包和校验值应作为同一组文件保留；后续代码更新使用新的版本号，不覆盖旧版附件。

每个安装包都内置完整对应源码，Release 仍应提供单独的源码包。GitHub 自动生成的 Source ZIP 不能替代包含固定依赖的对应源码检查。AGPL 及第三方许可证必须随二进制保留，不能只留下仓库链接。

## 自动构建

`.github/workflows/build.yml` 在 Intel macOS runner 进行离线构建和打包，PR 不获得仓库写入权限，成功后上传构建产物供下载。它不会安装包、连接 LTE 或自动发布 Release。

## 签名与公证

默认菜单栏应用是 ad hoc 签名，安装包未签名、未公证。正式签名需要自己的 Apple Developer ID Application / Installer 身份；签名凭据不得提交仓库。取得身份后应先签好所有分发的 Mach-O 及 app，再用 Developer ID Installer 签最终包，提交 Apple 公证并 staple，重新生成最终文件的 SHA-256。不要对已经签好的产物修改资源。

首次发行不提供自动更新器。后续更新前提醒用户：若正在使用 LTE，安装过程暂停助手会影响当前连接。保留原来的 LTE 启用选择，不能通过更新静默开启原本关闭的 LTE。

配置缺失时保持停用，不从旧运行状态推断启用意愿。卸载须先确认后台及数据会话已结束，再重置启用偏好、清理运行状态；重新安装默认停用。发布验证须覆盖首次安装、明确启用/停用后的升级、配置丢失、卸载及重装。
