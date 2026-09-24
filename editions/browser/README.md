# 拾页 Browser

通过本地浏览器界面采集贴吧帖子与截图，识别、校对、查询并归档小说信息。

## 启动

Windows 双击 `Start.cmd`；macOS 使用 `Start.command`；Linux 执行 `bash Start.sh`。首次准备目录内 Python 3.12 和依赖需要确认。Windows 运行包包含 `vendor` 中的 Python 和 uv，源码包不包含运行时。依赖优先从清华 PyPI 镜像安装，下载源在 `download-sources.conf` 中配置。运行不需要 Git，也不从项目仓库补下载代码。启动后自动打开浏览器，使用 Stop 入口结束服务。

内置 OCR 无需云端模型，也可配置多模态 API。支持起点、刺猬猫、菠萝包、番茄和 ESJ，书架截图支持同图多书。

`.runtime` 保存环境，`.local` 保存配置、任务和书库。Clean 入口会删除这些数据，执行前请备份。详细操作见 [使用指南](docs/USAGE.md)。

## 许可证

[MIT License](LICENSE)。第三方授权见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
