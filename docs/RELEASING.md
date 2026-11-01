# 公开仓库与发行

仓库：`https://github.com/Zachery-Liu/MagicBayLTE`，当前阶段保持 **Private**，Release 附件也遵循仓库访问权限。以后决定开放时再单独修改可见性，不因创建 Release 而公开仓库。

## 首次发布

1. 在自己的 GitHub 账号创建公开仓库 `MagicBayLTE`。不要另外生成 README / LICENSE，以免与本地初始提交冲突。
2. 上传这份独立项目目录的 Git 历史，不要上传上层个人工作目录。默认分支使用 `main`。
3. 在 Releases 创建 `v1.4.2`，先保存为 Draft / Pre-release。附上 `dist/MagicBayLTE-1.4.2-macOS-Intel.pkg`、`dist/MagicBayLTE-1.4.2-source.tar.gz`、`dist/SHA256SUMS.txt`，正文可用 `docs/RELEASE_NOTES_1.4.2.md`。
4. 在独立测试机器或测试启动卷验证全新安装、默认关闭、启用、关闭、退出界面、重新打开、更新和卸载。任何真实 LTE 出口切换都应先安排测试窗口，不能在构建时自动断网。
5. 检查无私人日志、状态、地址、凭据或抓包后，再公开 Release。早期硬件适配建议保留 Pre-release 标记，并收集相同 USB ID / 不同机器的反馈。

每个安装包都内置完整对应源码，Release 仍应提供单独的源码包。GitHub 自动生成的 Source ZIP 不能替代包含固定依赖的对应源码检查。AGPL 及第三方许可证必须随二进制保留，不能只留下仓库链接。

## 自动构建

`.github/workflows/build.yml` 在 Intel macOS runner 进行纯离线构建和打包，PR 不获得仓库写入权限，成功后上传构建产物供下载。它不会安装包、不连接 LTE、不自动公开 Release。首次 GitHub CI 运行情况需发布后单独确认。

## 签名与公证

默认菜单栏应用是 ad hoc 签名，安装包未签名、未公证。正式签名需要自己的 Apple Developer ID Application / Installer 身份；签名凭据不得提交仓库。取得身份后应先签好所有分发的 Mach-O 及 app，再用 Developer ID Installer 签最终包，提交 Apple 公证并 staple，重新生成最终文件的 SHA-256。不要对已经签好的产物修改资源。

首次发行不提供自动更新器。后续更新前提醒用户：若正在使用 LTE，安装过程暂停助手会影响当前连接。保留原来的 LTE 启用选择，不能通过更新静默开启原本关闭的 LTE。
