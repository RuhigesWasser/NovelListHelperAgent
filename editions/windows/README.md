# 拾页 Windows

Windows x64 桌面应用，在独立窗口中使用本地小说书单工具。

## 从源码构建

需要 .NET 8 SDK。先准备项目 Python 环境，再构建：

```powershell
& scripts/launcher.ps1 -Mode setup
& scripts/build_windows.ps1
```

产物为 `dist/Shiye-Windows-x64.zip`。完整解压后双击 `Shiye.exe`，不要只拷贝 exe。构建目录和输出目录可通过 BuildDirectory、OutputDirectory 参数指定。

默认程序包包含 .NET 运行时，以及 `vendor` 中的 Python 和 uv。首次使用经确认后，将锁定版本的依赖安装到 `.runtime`；默认使用清华 PyPI 镜像，失败后尝试 PyPI 官方源。项目代码、界面、脚本全部在包内，不需要 Git 或从项目仓库补下载。桌面窗口需要 WebView2 Runtime；也可运行 `Start.cmd` 使用浏览器界面。

下载源可在 `download-sources.conf` 中修改，只影响本应用。源码包不含 `vendor`，从源码准备 Python 时可通过 `PYTHON_MIRROR` 指定 python-build-standalone 镜像。

## 数据

环境位于 `.runtime`，配置、书库和窗口缓存位于 `.local`。关闭窗口会停止自己启动的后端；复用既有后端时保留该服务。清理前关闭窗口和服务并备份书库。

功能与平台限制见 [使用指南](docs/USAGE.md)。

## 许可证

[MIT License](LICENSE)。分发运行时和第三方组件时保留相应许可，见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
