# 拾页 / Shiye

从贴吧帖子和截图提取小说信息，通过官方平台查询核对，保存为本地书库。支持起点中文网、刺猬猫、菠萝包、番茄小说和 ESJ。

| 版本 | 用途 | 使用说明 |
| --- | --- | --- |
| Agent | 外部 Agent 按技能调用脚本，完成识图、查询和归档 | [Agent](editions/agent/README.md) |
| Browser | 本地后端与浏览器界面 | [Browser](editions/browser/README.md) |
| Windows | 独立窗口，自动管理本地后端 | [Windows](editions/windows/README.md) |

## 启动

Windows 双击 `Start.cmd`；macOS 使用 `Start.command`；Linux 执行 `bash Start.sh`。首次启动会询问是否下载私有 Python 3.12 和依赖，安装在本目录 `.runtime`，随后打开本地网页。

使用 Stop 入口停止服务。Clean 入口会删除本地环境和数据，包括书库，执行前请备份。

## 使用

1. 输入帖子链接或上传图片，选择内置 OCR 或已配置的多模态 API。
2. 校对识别文字，提取书单。书架截图支持同图多书。
3. 查询官方候选并核对作者，保存已确认的书籍。
4. 如需正文，在书库读取公开章节或选择目录条目。

配置、任务、素材和书库保存在 `.local`。书籍按 `题材/书名/书名.md` 组织，正文另存 `.txt`。

模型配置、账号保存、错误恢复和平台限制见 [使用指南](docs/USAGE.md)。

## 导出源码

```powershell
& .runtime/venv/Scripts/python.exe -B -m scripts.package_apps --all-projects projects
```

生成三个可独立使用的源码项目。输出目录必须尚不存在；如已有文件，请指定新的目录。Windows 源码包的编译方法见对应 README。

## 许可证

本项目采用 [MIT License](LICENSE)。第三方依赖和内容的授权范围见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
