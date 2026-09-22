---
name: sfacg-skills
description: "根据菠萝包（[sfacg.com](https://sfacg.com)）小说接口提取小说所需字段，或按书名搜索小说获取书 ID。当用户提供小说 ID 或 [book.sfacg.com](https://book.sfacg.com) 书籍链接，需要获取书名、作者、字数、状态、题材标签、内容简介、链接等信息；或仅提供书名（如推文中提及的小说）需要先查出书 ID 与链接时使用。技能直接输出精简 JSON，供后续按项目规范录入。适用于批量整理推文中提及的菠萝包小说的场景。"
---

# 菠萝包轻小说

从菠萝包小说接口（`GET https://api.sfacg.com/novels/{novelId}`、`GET https://api.sfacg.com/search/novels`）

拉取书籍数据，直接输出精简 JSON（仅含所需字段）；支持仅凭书名先查出书 ID。本技能不生成

Markdown 文档，后续生成书名.md 由项目 AGENTS.md 负责。

## 工作流



```
A\[输入书名或小说ID/链接] --> B{是书名还是ID/链接?}

B -->|仅书名| S\[search\_novel.py 按书名搜索]

S --> C\[得到 novelId]

B -->|ID/链接| C

C --> D\[fetch\_novel\_fields.py 调用小说接口]

D --> E\[提取所需字段]

E --> F\[输出精简 JSON]
```



1. 输入为书名（或部分书名关键词）时，先用 `search_novel.py` 搜索得到 novelId；

   输入为小说 ID、[book.sfacg.com](https://book.sfacg.com) 链接、推文来源中解析出的 ID 时直接确定 novelId。

2. 运行提取脚本（见下），获取书籍字段。

3. 落盘、索引与自检按项目 AGENTS.md 执行。

## 快速开始

按书名搜索（获取书 ID）：



```
python \<skill\_dir>/scripts/search\_novel.py 最强魔法少女               # 搜索，输出命中小说ID等

python \<skill\_dir>/scripts/search\_novel.py "最强魔法少女才不会白给雑鱼反派" --exact  # 仅精确同名

python \<skill\_dir>/scripts/search\_novel.py 变嫁 --size 20 --table    # 表格输出
```

按 ID / 链接提取字段：



```
python \<skill\_dir>/scripts/fetch\_novel\_fields.py 739541

python \<skill\_dir>/scripts/fetch\_novel\_fields.py https://book.sfacg.com/novel/739541/

python \<skill\_dir>/scripts/fetch\_novel\_fields.py 739541 123456
```



* 搜索默认输出 JSON：`novelId`、`novelName`、`authorName`、`novelUrl` 等，可配合

  `fetch_novel_fields.py` 提取完整字段。

* 提取直接输出精简 JSON：`novelId`、`novelName`、`authorName`、`platform`、`charCount`、

  `status`、`tags`、`intro`、`novelUrl`。

* 两个脚本均支持一次传多个输入，逐个输出。

## 按书名搜索（获取书 ID）

`search_novel.py` 通过菠萝包搜索接口（`GET https://api.sfacg.com/search/novels?key=<书名>`）按书名关键词

搜索，返回 `novelId` 等基本字段；得到书 ID 后再用 `fetch_novel_fields.py` 提取完整字段：



```
python \<skill\_dir>/scripts/search\_novel.py 变嫁 --exact --table   # 找到精确同名的书ID

python \<skill\_dir>/scripts/fetch\_novel\_fields.py <上一步的novelId>
```



* 部分关键词：按相关度排序，返回多本近似小说；完整书名通常精确命中唯一结果。

* `--exact`：仅保留与书名完全一致的匹配（忽略空白差异）；无精确命中时提示近似数量并返回非零退出码。

* `--size N`：每页返回数量（默认 20，最大 50）；接口支持 `page` 分页。

* 无命中或请求失败时返回非零退出码，便于脚本串联。

## 字段提取规则



* **题材标签**：合并 `sysTags` + `customTag` + 简介中「」括起的作者自标标签（如

  「变嫁」「1v1」），去重后以 JSON 数组输出。

* **字数**：`charCount` 原始字符数。

* **状态**：`isFinish` 为 true → 完结，否则 → 连载中。

* **简介**：原样复制 `expand.intro`，勿改写。

* **链接**：`https://book.sfacg.com/novel/{novelId}/`（实测页面地址）。

## 注意事项



* 请求头来自 OpenAPI 示例并已实测可用；`sfsecurity` 签名沿用示例值即可。

* 平台列表接口 `/novels/0/sysTags/novels` 不支持按书名过滤（实测 `novelname`/`novelName`

  参数均被忽略，结果与未过滤列表一致）；按书名搜索使用搜索接口

  `/search/novels?key=...`（同一套请求头）。

* 接口详情与错误处理见 [references/api.md](references/api.md)。

* 若接口失败：检查网络与输入是否有效，报错会指明具体输入。

* 中间结果落盘：批量查询时若需把 search 命中的 novelId、fetch 出的字段等中间 JSON 保存复用，一律写到 `项目根/tmp/`（如 `tmp/sfacg_ids.json`、`tmp/sfacg_fields.json`），不污染项目根；最终成稿由项目 AGENTS.md 负责写入各 `书名/` 目录。