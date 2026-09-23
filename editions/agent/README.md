# 拾页 Agent

外部 Agent 负责理解、识图和规划，通过 `.agents` 中的技能与脚本采集素材、查询书籍并归档。

## 准备环境

Windows 双击 `Setup.cmd`。首次下载 Python 3.12 和依赖需要确认，环境位于 `.runtime`。macOS/Linux 执行 `bash scripts/launcher.sh setup`，Python 位于 `.runtime/posix/<平台>/venv/bin/python`。

## 调用

先读取 `.agents/AGENT.md` 和所需技能，再运行工具：

```powershell
& .runtime/venv/Scripts/python.exe -B .agents/scripts/agent.py schema
'{"id":1,"action":"search_books","input":{"title":"书名","platform":"all"}}' | & .runtime/venv/Scripts/python.exe -B .agents/scripts/agent.py run
& .runtime/venv/Scripts/python.exe -B .agents/scripts/agent.py serve
```

`schema` 返回工具清单；`run` 接收一个 JSON 请求；`serve` 每行接收一个请求，同一进程可复用内存会话。标准输出为 JSON，进度写标准错误。本版不自带 Agent 模型，也无需运行网页服务。

支持起点、刺猬猫、菠萝包、番茄和 ESJ。工具覆盖抓帖、OCR、提取书单、搜索、详情、目录、章节读取和归档。书库与状态位于 `.local`。

功能设置与平台限制见 [使用指南](docs/USAGE.md)。

## 许可证

[MIT License](LICENSE)。第三方授权见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
