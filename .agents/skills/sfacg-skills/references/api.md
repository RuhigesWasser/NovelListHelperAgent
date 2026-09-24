# 菠萝包字段协议

当前适配器读取 api.sfacg.com 的 GET /search/novels 和 GET /novels/{id}，接口变动时更新适配器。

搜索参数：key 为书名关键词，page 从零开始，size 为每页数量。返回候选 ID、标题、作者、封面和详情链接；exactMatch 仅表示去除空白后的标题一致，不代表作者已核对。

详情输出：novelId、novelName、authorName、platform、charCount、status、tags、intro、novelUrl。标签按来源顺序去重。网络和响应格式错误以异常或 CLI 错误列表表示。

公共客户端请求参数用于接口兼容，不对应用户的私人登录账号。服务接口和可访问范围由平台决定。
