# tieba-skills 参考文档

## 1. 中间 JSON 结构（fetch_thread.py 输出）

```json
{
  "tid": 10085546563,
  "url": "https://tieba.baidu.com/p/10085546563",
  "fname": "健康比赛选手",
  "title": "帖子标题",
  "floor_count": 59,
  "floors": [
    {
      "floor": 1,
      "text": "楼层正文（无正文为空串；含小尾巴文本）",
      "images": [
        {"url": "https://tiebapic.baidu.com/forum/pic/item/xxx.jpg?tbpicau=...",
         "file": "C:\\...\\f1_1_<hash>.jpg",
         "hash": "<32位十六进制图床hash>"}
      ]
    }
  ]
}
```

字段说明：

| 字段 | 说明 |
|---|---|
| `floors[].floor` | 楼层号（首楼=1） |
| `floors[].text` | 楼层正文（`post.text`，含小尾巴），无正文为空串 |
| `floors[].images[].url` | 图床 URL（带时效签名 `tbpicau`，过时失效） |
| `floors[].images[].file` | 已下载到本地的图片绝对路径（大图已自动压缩） |
| `floors[].images[].hash` | 图床 hash，同一图片跨楼层重复出现时 hash 相同、复用同一文件 |

## 2. 最终合并数组（交付给下一步）

```json
[
  {"text": "……", "images": ["OCR文本1", "OCR文本2"]},
  {"text": "……", "images": []}
]
```

仅 `text` 与 `images` 两字段；`images` 元素为图片 OCR 文本，纯插图无文字时为 `""`。

## 3. aiotieba 用法要点（脚本已封装，供排查/改动参考）

```python
from aiotieba import Client

async with Client() as client:                       # 匿名 WebClient
    posts = await client.get_posts(tid, pn=1, rn=30) # 获取主题帖楼层
    # posts.objs        -> list[Post] 楼层列表
    # posts.thread      -> Thread_p  标题/正文
    # posts.forum       -> Forum_p   吧名
    # posts.page        -> Page_p    页码/总数
    # posts.has_more    -> bool      是否有下一页
    # post.floor        -> 楼层号
    # post.text         -> 楼层正文（含小尾巴）
    # post.contents.imgs-> list[FragImage_p] 图片碎片
    #   img.origin_src  -> 原图链接  img.big_src -> 960px  img.src -> 720px
```

- 楼层仅取主题帖楼层（`get_posts` 的 `objs`），不含楼中楼（`post.comments`）。
- 翻页：`pn` 递增直到 `has_more` 为 False；脚本在翻页间 sleep 0.3s 降低风控概率。
- 匿名读取公开帖可行（已用 `https://tieba.baidu.com/p/10085546563` 实测：2 页、59 层、约 80 张图）。
- 若帖子删除/隐藏/受限，`get_posts` 抛异常（如 `TbError`），脚本会输出错误信息并以非零码退出。

## 4. 图片下载与预处理

- 默认缓存目录：`项目根/tmp/tieba_<tid>`（项目根 = 含 AGENTS.md/AGENT.md 或 .agents 的目录），可用 `--img-dir` 覆盖。
- 下载请求头：`User-Agent: Mozilla/5.0 ...` + `Referer: https://tieba.baidu.com/`（实测可不带 Referer，仍带上更稳）。
- 图片 URL 必须**当次抓取当次下载**：`tbpicau` 是时效签名，过期后 URL 失效。
- 预处理：文件 > 3.5MB 或长边 > 2048px 时，用 Pillow 缩到长边 2048、JPEG q85（保证 Read 识图可读、体积可控）。未安装 Pillow 时跳过并打警告。

## 5. 常见失败与排查

| 现象 | 原因与处理 |
|---|---|
| `无法识别贴吧帖子链接或 tid` | 输入不是 `/p/<数字>`、`tid=<数字>` 或纯数字，检查链接 |
| `ModuleNotFoundError: aiotieba` | 未自动安装成功；手动 `pip install aiotieba` |
| `TbError ... 需要登录/帖子不存在` | 帖子受限或删除；匿名无法读取，明确告知用户，不做登录绕过 |
| 图片下载失败/超时 | 网络波动（脚本已重试 1 次）；帖图极多时可 `--size big` 减小体积 |
| `[警告] 未安装 Pillow` | `pip install pillow` 后重跑，否则大图可能因超 5MiB 无法识图 |
| JSON 里图片 URL 打不开 | `tbpicau` 已过期，重新运行抓取脚本 |
