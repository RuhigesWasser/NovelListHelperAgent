---

name: tieba-skills

description: " 抓取任意百度贴吧帖子链接的楼层正文与楼层内嵌图片，并对图片（大概率是小说详情页 / 简介截图）做识图转写，最后合并为一个数组 JSON 返回给下一步处理。当用户提供贴吧帖子链接（形如 [https://tieba.baidu.com/p/10085546563](https://tieba.baidu.com/p/10085546563) 或纯数字 tid），需要提取推文楼层文本、截图中的书名 / 作者 / 简介信息，或把贴吧帖子内容整理成结构化 JSON 时使用。技能不生成 Markdown 文档，后续按书名整理由项目 AGENTS.md 负责。"



---

# 贴吧技能包

输入任意百度贴吧帖子链接，用 `aiotieba` 匿名读取全部楼层，输出两部分内容：



1. **楼层正文文本**；

2. **楼层内嵌图片**（贴吧楼层里大概率是小说详情页 / 简介的截图），下载后由 AI 视觉识图转写为文字。

最终合并为一个**数组 JSON**，返回给下一步（按项目规范录入书名.md 等）处理。

## 工作流



```
A\[输入贴吧帖子链接/tid] --> B\[fetch\_thread.py 抓取楼层正文+下载图片]

B --> C{楼层图片?}

C -->|有| D\[AI 逐张识图：用 Read 打开本地图片，转写 OCR 文本]

C -->|无| E

D --> E\[合并为数组 JSON]

E --> F\[写入 tmp/tieba\_帖子ID.json 并返回给下一步]
```



1. 从链接 / 输入解析出 tid（支持 `https://tieba.baidu.com/p/10085546563?fr=frs`、`/p/数字`、`tid=数字`、纯数字）。

2. 运行抓取脚本（见下），得到每层 `text` 与图片本地路径（图片已自动下载、大图已自动压缩）。

3. 对每个**去重后**的图片文件用 Read 工具识图，转写图片中的文字。

4. 按「输出格式」合并为数组 JSON：写入 `项目根/tmp/tieba_帖子ID.json`（中间结果一律放 `tmp/`，不污染项目根），并在回复中返回该数组供下一步使用。

## 快速开始



```
python 技能目录/scripts/fetch\_thread.py https://tieba.baidu.com/p/10085546563?fr=frs

python 技能目录/scripts/fetch\_thread.py 10085546563 --out D:\tmp\thread.json

python 技能目录/scripts/fetch\_thread.py 帖子ID --img-dir D:\tmp\imgs --size big
```



* 默认输出中间 JSON 到 stdout（含每层 `floor`、`text`、`images[].url/file/hash`）；加 `--out` 同时写入文件。

* 图片默认缓存到 `项目根/tmp/tieba_帖子ID` 目录；可用 `--img-dir` 改到其他位置。

* 图片默认下载原图（`--size origin`）；帖图极多、带宽紧张时可 `--size big`（960px）或 `src`（720px）。

* `aiotieba` 未安装时脚本会自动 `pip install`；图片过大时自动用 Pillow 压缩（未装 Pillow 则跳过并警告）。

## 输出格式（最终合并数组）

严格按以下结构，每层一条，仅保留 `text` 与 `images` 两个字段：



```
\[

&#x20; {"text": "楼层正文文本（无正文则为空串）", "images": \["第1张图的OCR文本", "第2张图的OCR文本"]},

&#x20; {"text": "……", "images": \[]}

]
```



* `images` 的元素**直接是图片的 OCR 文本**（识图转写结果），不是 URL。

* 图片是纯插图 / 封面（无文字）时，OCR 文本为空，写 `""`，不删除该位置。

* 最终数组写入 `项目根/tmp/tieba_帖子ID.json`（项目根 = 含 AGENTS.md/AGENT.md 或 .agents 的目录；中间结果 JSON 一律放 `tmp/`，不放项目根），并整体返回给下一步。

## 识图规则



* 用 Read 工具打开 `images[].file` 指向的本地图片，读取「OCR」表中的文本作为该图的 OCR 文本。

* 同一 hash 的图片（跨楼层重复出现）只识图一次，结果复用。

* 识别框文字过小 / 过密时，适当放大或分块再读；以图片上实际出现的文字为准，不脑补。

* 纯插画类图片（无文字）OCR 文本记 `""`；描述性内容（人物 / 场景）不写入 images。

## 注意事项



* **匿名读取**：公开帖无需登录即可读取（已实测）。若脚本报错提示需要登录 / 帖子受限，说明该帖无法匿名读取，明确告知用户并停止，不做登录绕过。

* 图片 URL 带有时效签名（`tbpicau`），必须在抓取当次完成下载与识图；不要在后续复用旧 JSON 里的图片 URL。

* 帖子多页时脚本自动翻页（默认每页 30 层）；楼层仅取主题帖楼层，不含楼中楼。

* 失败排查与字段说明见 [references/api.md](references/api.md)。