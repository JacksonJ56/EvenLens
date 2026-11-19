# 公众舆情评论导入

先在「实验选择」选择当前热点和「公众舆情分析」，展开「使用已有授权评论」，选择 JSON / CSV 文件，确认授权后导入，再点击原有「执行」。没有新增必填链接或关键词输入框。

文件必须来自你有权使用的数据；不要上传不必要的昵称、用户 ID、手机号、头像等个人信息。系统不把导入数据冒充在线采集。文件最大 4 MB，最多 100 个帖子、10000 条输入记录，实际按配置保留前 20 个帖子、每帖前 50 条有效一级评论、总计最多 1000 条。

## JSON

顶层包含 `posts` 和 `comments` 数组。以下只是字段模板，必须替换成你的真实资料，不能把占位文字当评论分析：

```json
{
  "posts": [
    {
      "id": "真实帖子ID",
      "platform_id": "weibo",
      "url": "https://m.weibo.cn/detail/真实数字帖子ID",
      "title": "真实帖子标题",
      "published_at": null
    }
  ],
  "comments": [
    {
      "platform_id": "weibo",
      "post_id": "真实帖子ID",
      "comment_id": "真实评论ID",
      "source_rank": 1,
      "sort_mode": "unknown",
      "content": "真实评论原文",
      "created_at": null,
      "like_count": null,
      "parent_comment_id": null,
      "source_url": null,
      "collected_at": null
    }
  ]
}
```

- 平台 ID：`xiaohongshu`、`douyin`、`kuaishou`、`bilibili`、`weibo`、`tieba`、`zhihu`。快手映射已保留，但当前热点目录没有快手入口，不能单独新增它。
- 微博仅接收可转换为数字 mid 的帖子；B站 `id` 使用 URL 中的 `BV...` 或 `av...`；小红书使用 24 位笔记 ID；知乎使用回答/文章/视频 ID，问题聚合页不是可直接采集的帖子。
- 帖子链接必须与平台和 ID 对应。小红书链接可保留原有 `xsec_token` 查询参数；系统不会生成或绕过这些凭据。
- 同一帖子下的评论按文件顺序截取，**不会按点赞数重排**。`source_rank` 是原始来源顺序；未知可留空，不要虚构排名。
- `sort_mode`：`hot`（来源明确热门）、`score`（评分排序）、`time`（时间排序）、`unknown`（无法确认）。导入文件中的声明不会被当作系统已独立核验。
- 时间使用带时区 ISO 8601，例如 `2025-04-04T10:20:00+08:00`，未知使用 `null`。不要用文章发布日期替代评论时间。
- 一级评论 `parent_comment_id=null`。回复应排在父评论之后，且父评论必须在保留样本内；回复不计入一级评论统计分母。
- 同一平台/帖子/评论 ID 去重；不同 ID 的同文评论保留。清洗后的文本和原始文本都保留，不额外保存用户画像。
- 文件导入后只绑定当前分区、平台、实际 feed ID 和热点 ID。切换到其他热点后，必须为新热点重新导入。

## CSV

每行一条评论，首行字段名如下；可选字段留空，文本含逗号或换行时按 CSV 规范加双引号：

```csv
platform_id,post_id,comment_id,content,post_url,post_title,source_rank,sort_mode,created_at,like_count,parent_comment_id,source_url,collected_at
```

CSV 的 `post_url`、`post_title` 用于构造帖子对象，其余字段与 JSON 评论一致。文件编码为 UTF-8（可带 BOM）。同一平台的不同榜单、不同事件不要混入一个文件。

系统能核对格式、链接平台、数据归属和引用，但不能仅凭文件证明评论真实存在或与事件相关。请核查来源；报告会明确保留这项局限。
