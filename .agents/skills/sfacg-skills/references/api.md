# 菠萝包小说接口参考

来源：用户提供的 OpenAPI 3.0.1 文档（api.sfacg.com 正式环境）。

## 接口

`GET https://api.sfacg.com/novels/{novelId}` — 小说详情（提取字段）
`GET https://api.sfacg.com/search/novels?key={书名}` — 按书名搜索（获取书ID，见"按书名搜索"专节）

### 小说详情

`GET https://api.sfacg.com/novels/{novelId}`

- `novelId`：小说 ID（路径参数），例如 `739541`。
- `expand`（query，可选）：逗号分隔的扩展字段名，用于取回所需字段：

```
chapterCount,bigBgBanner,bigNovelCover,typeName,intro,fav,ticket,pointCount,tags,sysTags,
signlevel,discount,discountExpireDate,totalNeedFireMoney,rankinglist,originTotalNeedFireMoney,
firstchapter,latestchapter,latestcommentdate,essaytag,auditCover,preOrderInfo,customTag,topic,
unauditedCustomtag,homeFlag,isbranch,essayawards
```

## 请求头

| Header | 值 |
|---|---|
| Host | `api.sfacg.com` |
| Accept-Charset | `UTF-8` |
| Authorization | `Basic YW5kcm9pZHVzZXI6MWEjJDUxLXl0Njk7KkFjdkBxeHE=` |
| User-Agent | `boluobao/4.8.14(android;28)/BDFZH2/31cc3dcc-e28f-33fb-8ec7-dae2b890eeaf` |
| Accept | `application/vnd.sfacg.api+json;version=1` |
| Accept-Encoding | `gzip`（响应为 gzip 时需解压） |
| sfsecurity | `nonce=5BAA32A6-9AB7-4CF6-8BB1-1B964F99FDF6&timestamp=1673616403984&devicetoken=31CC3DCC-E28F-33FB-8EC7-DAE2B890EEAF&sign=1F2A670DF33290D8E13DDBF161DE6137` |

以上请求头来自 OpenAPI 示例并已实测可用（2026-09 验证返回 HTTP 200）。`sfsecurity`
的签名算法未知，实测沿用示例值可正常返回；若未来接口收紧校验导致失败，需更换为有效签名。

## 响应结构

```jsonc
{
  "status": { "httpCode": 200, "errorCode": 200, "msgType": 0, "msg": null },
  "data": {
    "novelId": 739541,
    "novelName": "书名",
    "authorName": "作者",
    "charCount": 505100,        // 总字数（字符）
    "isFinish": false,          // 是否完结
    "lastUpdateTime": "2026-05-01T23:54:12",
    "novelCover": "https://rss.sfacg.com/...",
    "expand": {
      "chapterCount": 142,      // 章节数
      "typeName": "都市",        // 题材分类
      "intro": "内容简介...",     // 简介，末尾常带「变嫁」「1v1」等自标标签
      "sysTags": [ { "sysTagId": 125, "tagName": "纯爱" }, ... ],   // 平台标签
      "customTag": [],           // 自定义标签
      "firstChapter": { "title": "...", "chapId": 9004596, "addTime": "..." },
      "latestChapter": { "title": "...", "chapId": 9714887, "addTime": "..." },
      "bigNovelCover": "https://rss.sfacg.com/..."
    }
  }
}
```

## 技能输出字段

`fetch_novel_fields.py` 将接口数据精简为以下字段输出 JSON：

`novelId`、`novelName`、`authorName`、`platform`（固定「菠萝包」）、`charCount`、
`status`（完结/连载中）、`tags`（合并 `sysTags` + `customTag` + 简介「」标签，去重）、
`intro`、`novelUrl`。

本技能只输出字段数据，不生成 Markdown 文档；书名.md 文档的生成与目录组织按项目
AGENT.md 规范执行。

## 按书名搜索（获取书ID）

`GET https://api.sfacg.com/search/novels`

按书名关键词搜索小说，返回命中列表。请求头与详情接口一致（见上表）。

| 参数 | 位置 | 必填 | 说明 |
|---|---|---|---|
| key | query | 是 | 书名或关键词，需 URL 编码，如 `最强魔法少女` |
| page | query | 否 | 页码，默认 0 |
| size | query | 否 | 每页数量，默认 20，实测上限 50 |

### 响应结构

```jsonc
{
  "status": { "httpCode": 200, "errorCode": 200, "msgType": 0, "msg": null },
  "data": {
    "items": [
      {
        "novelId": 739541,
        "novelName": "最强魔法少女才不会白给雑鱼反派",
        "authorName": "睡不醒的大大",
        "categoryId": 0,
        "novelCover": "https://rss.sfacg.com/web/novel/images/NovelCover/Big/2025/03/8c52b9fc-....jpg"
      }
    ]
  }
}
```

### 说明

- 按相关度排序；完整书名通常精确命中唯一结果，部分关键词返回多本近似小说。
- 命中项仅含基本字段（不含字数/状态/简介），得到 `novelId` 后需再用
  `GET /novels/{novelId}` 提取完整字段。
- 实测（2026-09）：列表接口 `/novels/0/sysTags/novels` 的 `novelname`/`novelName`
  参数不生效（结果与未过滤列表一致），按书名搜索请使用本接口。

## 错误处理

- 非 200 / `errorCode != 200`：按 status.msg 提示。
- 网络异常 / 非 JSON 响应：报错并给出输入定位。
- 无法解析输入（非数字、非链接）：明确提示支持的格式。
