# 发布规格与结果核对

## 严格输入

```json
{
  "title": "我的创作记录",
  "content": "今天完成的一张练习图。",
  "content_format": "text",
  "hashtags": ["创作记录"],
  "topic_ids": [],
  "images": ["picture.png"],
  "post_type": "1",
  "original": true
}
```

只允许这些字段。content 是非空字符串；content_format 为 text 或 html，默认为 text。title 默认为空；列表默认为空。topic_ids 只接受数字字符串。post_type 为字符串 "1" 或 "3"，默认 "1"。original 为布尔值，默认 true。内容与标签可能由原版 Post.build 渲染、规范化，facade 不重写原版渲染器。

图片限本地 PNG/JPEG/GIF，每张不超过 20 MiB；格式头和尺寸必须可被原版读取。不会下载远程图片。HTML 内嵌媒体、CSS 资源、cover_url、visibility、edit_link_id 等扩展留给用户明确操作的原版 CLI，本流程拒绝这些字段。JSON 中不能提供 draft 或 mode，模式只来自必选的 `--mode draft|public`。

## 快照与确认

`plan SPEC --account ALIAS --mode draft --out OPERATION` 要求 OPERATION 尚不存在且父目录已经存在。完成所有输入检查后，复制图片到 media/，写入 plan.json。SPEC 内相对图片路径按 SPEC 的父目录解析；发布时不会重新读取原图片路径。

`show OPERATION` 在离线校验后输出完整计划。计划字段：schema_version、account、mode、spec、media、cli_version、wheel_sha256、kit_version、runtime_manifest_sha256、approval_sha256。spec.images 是安全的 operation 相对路径。media 每项有 path、sha256、bytes。最后一个哈希绑定除其自身外的规范 JSON，包含账号、模式、正文、标签、冻结图片和固定运行时。

确认对象必须是 show 的结果。提交命令需要匹配的 `--approval` 和 `--confirm`。manifest 是完整性检查，不是针对恶意重写整个包的数字签名；应从可信渠道取得包并核对发布的校验和。

## 单次尝试

submit 先重新验证所有字节，再调用原版 `account status ALIAS --online`。身份通过后再验证快照，把已校验图片复制到私有临时目录。保留 attempt.json 后，先用原版 `--account ALIAS upload IMAGE... --confirm` 上传这些副本。上传结果必须与图片数量一致，每项含可信 `imgheybox` 数字后缀 `.max-c.com` 主机的 HTTPS URL 和正整数宽高。

facade 使用原版 Post 渲染文本，将上传 URL 转义后追加为带 `data-width`、`data-height` 的内嵌 HTML img 节点。随后以标准输入 JSON 调用原版 `--account ALIAS publish - --confirm`，指定 content_format=html、images=[]。仅 public 计划添加 `--publish`。用户批准的 spec/plan 不变；此转换仅适配图片提交格式，不增加远程图片来源。

原版 .7 直接 publish 的 HTML 加独立 img 块在实测中可能被服务端丢弃，即使返回 link_id 也不能证明图片保存。AI 图片发帖应走本 facade，不能用原版 images 字段绕过适配。独立 upload 命令仍可正常使用。

任何上传或发帖子进程启动前，以独占方式创建 attempt.json。一旦存在，无论上次是否超时、进程是否崩溃，都不再上传或发布。此保证只覆盖这个操作目录，不是服务端全局 exactly-once。上传失败、结果格式不符或发帖失败均保守返回 outcome_unknown；图片可能已上传而帖子未创建，不要自动重试或删除记录。

## 状态与退出码

| 状态 | 退出码 | 含义 |
| --- | --- | --- |
| prepared | 0 | 仅本地冻结 |
| show 的计划对象 | 0 | 离线完整性通过，没有发布状态 |
| acknowledged | 0 | 创建得到 link_id，但不是完整验证 |
| outcome_unknown | 3 | 已保留尝试记录，结果未知 |
| refused | 2 | 当前操作被拒绝或输入无效 |

receipt.json 只保存状态、批准哈希、可选 link_id/规范 URL、安全原因和核对布尔值。没有 CLI stderr、签名、凭据或原始回包。

## 核对范围

reconcile 永远不发布、不清理 attempt.json。没有 link_id 时返回 outcome_unknown，要求用户查看自己的草稿/帖子。已有 link_id 时调用原 CLI 的 drafts 或 posts 列表，以已知字段 linkid 匹配并比较 title、description、draft。列表描述可能截断，图片列表也不能证明原图字节一致；因此当前版本只记录有限的 readback 布尔值，保持 acknowledged。

当前版本不输出 verified_draft 或 verified_public。自己的列表出现帖子不等于匿名公众可见，也不等于正文和所有图片都已完整核对。用户另行核验可以补充证据，但不能把创建回执自动转成公开成功。读取失败也不允许重新提交。

本地快照含待发布内容，应放在用户私有输出目录，不提交到版本库或发布包。具有本机写权限的其他进程不在隔离保证内；哈希与独占文件不是操作系统沙箱。
