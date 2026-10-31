# 构建与重新链接

需要 Intel macOS、Apple Xcode Command Line Tools、Python 3.9+、clang、swiftc、make、pkgbuild 和 productbuild。无需 Homebrew，无需联网下载依赖。

```sh
python3 build_offline.py
python3 MenuBarLTE/build_app.py
python3 scripts/package_release.py
python3 scripts/verify_release.py
```

前两步分别构建并验证后端和菜单栏应用，第三步核对构建清单、生成对应源码压缩包和安装包。产物位于 `dist/`，不会安装到当前机器，不会启停正在运行的 LTE。

`build_offline.py` 先校验并解压 `third_party/libusb-1.0.29.tar.bz2`，以 `-arch x86_64 -mmacosx-version-min=13.0` 静态构建 libusb，再生成 MBIM 引擎并运行 Python 单元测试、C 地址 / 未定义行为检查。`test_data.py` 是需要明确 opt-in 的硬件诊断工具，不参与离线构建，也不装入用户运行目录。历史全局出口版本仅用于开发；安装包只携带 managed 引擎和网络观察器。

修改 MBIM 引擎请编辑 `adapt_engine.py` 或 `magicbay_*.h`。`magicbay_lte.c` 是生成文件。上游源文件以 `reference-cellular/UPSTREAM.json` 固定提交及 SHA-256，源码 ZIP 无需嵌套 Git 仓库也能构建。

## 使用修改后的 libusb

首次构建后，编辑已解压的 `libusb-1.0.29/` 源码，在该目录运行 `make -j2`，然后重新运行上面三个构建命令。构建脚本会保留同一构建标记下的 libusb 修改，并重新链接所有 LTE 引擎。也可删除 `.magicbay-build-flags` 后重新配置构建。

原始依赖压缩包及 LGPL 许可证随项目源码与安装包一起提供；本项目全部应用源码及构建 / 安装脚本也随包提供，因此接收者可以修改库并重新链接。请保留第三方声明；重新分发修改版本时也要提供完整对应源码。原始压缩包的来源与校验值见 `third_party/README.md`。

默认代码签名为 ad hoc，不需要任何私有证书。自行构建的包可以按 macOS 用户授权流程安装；脚本不绕过系统安全机制。正式 Developer ID 签名 / 公证见发布说明。

## 验证范围

1.4.0 的运行逻辑已在原开发机完成受控 LTE 单目标传输及返回 Wi-Fi 后旧连接无法继续传输的验证。公开目录会重新离线构建。安装包还应在独立、具备模块的测试机器验证安装 / 更新 / 卸载；仅验证包结构不能代替这一项。macOS 13/14、其他固件及其他机器尚未验证。
