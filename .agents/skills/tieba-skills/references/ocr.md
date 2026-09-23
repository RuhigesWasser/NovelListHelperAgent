# OCR 命令行

使用项目的 Python 环境运行脚本：

```text
python .agents/skills/tieba-skills/scripts/ocr.py 图片路径 --ocr builtin --out tmp/result.json
python .agents/skills/tieba-skills/scripts/fetch_thread.py 帖子URL --ocr builtin --raw-out tmp/raw.json --out tmp/result.json
```

`--ocr none` 仅采集；builtin 使用本地 OCR；llm 使用多模态 API。日文、韩文模型需先确认下载到项目目录，再以 `--language japan` 或 `--language korean` 选择。

LLM 默认读取最后选中的本地配置，也可通过 OCR_LLM_BASE_URL、OCR_LLM_MODEL、OCR_LLM_API_KEY 环境变量覆盖。`--llm-api-key-env` 指定另一个密钥环境变量。

支持 `--llm-protocol`、`--llm-endpoint-mode`、`--llm-auth`、`--llm-key-header`、`--llm-token-field`、`--llm-timeout`、`--llm-max-tokens`、`--llm-stream` 和 `--llm-no-stream`。完整参数运行 `--help` 查看。

输出保持楼层、图片顺序，同图重复素材只识别一次。失败时保留原始素材与已有结果；只保存成功取得的文字。模型不支持图片、响应截断或流式中断时返回错误。
