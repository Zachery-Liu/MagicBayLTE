# 项目结构

根目录保留 README、许可证、版权声明和贡献说明。源码与构建产物按职责分开：

| 目录 | 内容 |
| --- | --- |
| `app/` | AppKit / SwiftUI 菜单栏界面、图标资源及应用构建脚本 |
| `backend/` | Python 后台服务、连接管理、切换策略和本地控制协议 |
| `engine/` | MBIM 原生引擎适配脚本、协议头文件、USB 和网络观察器 |
| `tools/` | 显式运行的开发诊断工具，不随软件安装 |
| `scripts/` | 离线构建、依赖构建、源码归档、打包及验证脚本 |
| `tests/` | Python 单元测试和使用模拟 USB / 网络接口的 C 测试 |
| `packaging/` | 安装前后脚本及卸载程序 |
| `third_party/` | 固定版本的上游引擎源码及 libusb 源码压缩包 |
| `licenses/` | 第三方许可证全文 |
| `docs/` | 构建、架构和发行文档 |
| `.github/workflows/` | GitHub Actions 构建流程 |
| `build/` | 本地生成文件、依赖、缓存、运行文件暂存区和测试结果，不提交 Git |
| `dist/` | 发行安装包、完整源码包及校验文件，不提交 Git |

## 构建输出

```text
build/
├── app/          # 菜单栏应用和应用构建清单
├── cache/        # Swift / Python 编译缓存
├── deps/         # 解压并构建的第三方依赖
├── engine/       # 生成的 C 引擎源码及上游来源记录
├── runtime/      # 安装包所需的平铺后台文件
├── tools/        # 仅供开发使用的诊断引擎
└── validation/   # 构建清单和离线测试输出
```

安装后的应用与后台目录不受源码目录划分影响。开发时通过 `scripts/build.py` 生成后台文件，通过 `app/build_app.py` 生成应用，再用 `scripts/package_release.py` 打包。
