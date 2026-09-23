# 拾页 Windows

Windows x64 桌面应用，在独立窗口中使用本地小说书单工具。

## 从源码构建

需要 .NET 8 SDK。先准备项目 Python 环境，再构建：

```powershell
& scripts/launcher.ps1 -Mode setup
& scripts/build_windows.ps1
```

产物为 `dist/Shiye-Windows-x64.zip`。完整解压后双击 `Shiye.exe`，不要只拷贝 exe。构建目录和输出目录可通过 BuildDirectory、OutputDirectory 参数指定。

默认构建包含 .NET 运行时；使用机器需要 WebView2 Runtime。首次使用时会询问是否下载目录内 Python 环境。也可以运行 `Start.cmd` 使用浏览器界面。

## 数据

环境位于 `.runtime`，配置、书库和窗口缓存位于 `.local`。关闭窗口会停止自己启动的后端；复用既有后端时保留该服务。清理前关闭窗口和服务并备份书库。

功能与平台限制见 [使用指南](docs/USAGE.md)。

## 许可证

[MIT License](LICENSE)。分发运行时和第三方组件时保留相应许可，见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
