# 采集接口

通过 aiotieba 的异步 Client.get_posts(tid, pn, rn) 获取帖子分页。逐页读取至 has_more 为假。只覆盖帖子楼层，不递归采集楼中楼。

原始 JSON 包含 tid、url、title、fname、floor_count、floors。每个楼层包含 floor、pid、page、text 和 images；每张图片包含 url、file、hash。pid 与 page 用于保留来源定位，file 为下载后的本地路径。

`preserve_images=True` 保留图片分辨率；默认外部 Agent 浏览方式可将过大的预览缩小。内置 OCR 按原图分块识别。无法访问帖子或下载失败时返回错误，不将未下载图片当作已识别。
