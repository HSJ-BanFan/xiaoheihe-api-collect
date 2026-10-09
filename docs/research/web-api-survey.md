# 小黑盒 Creator Web 接口候选与继承探测记录

本页整理截至 2026-10-09 的静态候选和两批继承探测记录，不是全平台接口清单。
当前 CLI 候选版为 `0.6.0rc1`。本页不声明该版本已完成登录、上传、草稿或公开发布验收。
公开记录不包含测试账号别名、账号 ID、凭据或原始服务端错误。

## 静态证据范围

`web-endpoints.json` 保留 63 条路径候选。候选来自有限前端文件中的路径字符串，
其中可能包含页面路由、未使用代码或接口路径；出现一个字符串不等于存在可调用 API。
这个数字既不是小黑盒全部接口数量，也不是经过完整功能验收的接口数量。

当前 Creator 页面取得的 `index-BQ64EhAG.js` 与归档副本的 SHA-256 一致：

```text
b30c3e28b15d69e57e918bd57b21803ce95e8cc5f83e9d33614ab8614d553a0a
```

该哈希只标识所检查的脚本字节，不证明网页所有资源均已读取，也不证明服务端契约未变。
对该脚本的有限源码匹配产生 36 条有方法证据的路径，另有 27 条方法未知。
提取记录 `source-methods.json` 的 SHA-256 为：

```text
821f53e829d727c7cd484289bbea2bd9fd22057a678b3f2c68557b22f3f29f6a
```

[web-exact-methods.json](web-exact-methods.json) 按这份提取记录重建。
`methods: null` 表示没有匹配证据，不能默认填成 POST。
例如 `/account/restore_login` 的源码方法为 GET，发帖路径 `/bbs/app/api/link/post` 为 POST，
而 `/bbs/app/link/tree/v2` 在这份有限匹配中的方法仍未知。
函数名、HTTP 方法和接口可用性是不同证据；GET 也可能改变状态。

[web-endpoint-details.json](web-endpoint-details.json) 保留继承的签名分类作为
`inherited_signing_claim`，并明确 `signing_verified: false`。
它不把先前的签名猜测转成已验证契约。

## 两批探测记录不能合并成一次验收

两份继承记录分别有 63 行，结果如下。没有在此次文档整理中重新执行它们。

| 记录文件 | ok | error | 跳过 | 当前候选重新实测 |
|---|---:|---:|---:|---|
| [web-endpoints-test-report.json](web-endpoints-test-report.json) | 11 | 42 | 10 | 否 |
| [web-endpoints-verified.json](web-endpoints-verified.json) | 14 | 39 | 10 | 否 |

第二个文件名保留了历史命名，其中的 `verified` 不表示当前版本已通过验收。
每份公开文件保留原记录哈希、各行结果、当时记录的方法和签名模式，去除原始错误和消息。
`recorded_method` 表示当时的记录值，不是源码确认的方法。不能用它覆盖静态方法证据。

`ok` 只表示该行被记录为成功响应，不能推出完整参数正确、所有返回字段正确、身份有效或写操作成功。
`error` 的原因没有逐项确认，因此统一保留 `cause_verified: false`。
缺参、会话类型、版本限制、暂时故障和路径性质都不能仅凭旧错误字符串定论。
10 条跳过记录没有执行结果；跳过不代表该路径已证明安全。
继承的守卫清单也不是所有写操作的完整清单，不能直接据此启动新一轮批量探测。

旧记录中的上传信息分配成功，不等于已经上传图像、读回 CDN 字节或发布作品。
这里没有足够证据断言“发帖必须绑定微信网页会话”，也不能把某次拒绝归因于 App/Web 会话隔离。

## 当前 CLI 的实现边界

`0.6.0rc1` 支持显式 `app` 或 `web`。未记录模式的旧配置仍按 App 处理。
`--protocol` 只覆盖本次命令；按账号保存模式需要明确执行配置命令。
请求失败后不会改用另一种协议重试。

```console
xhh-sdk --protocol web doctor --offline
xhh-sdk account configure <alias> --set protocol_mode=web --confirm
xhh-sdk account login <alias> --method creator --timeout 600 --confirm
xhh-sdk --protocol web account status <alias> --online
xhh-sdk --account <alias> --protocol web creator-options
xhh-sdk --account <alias> --protocol web edit-info <link-id>
```

`creator` 打开官方创作者页面，由用户使用小黑盒 App 扫码或页面短信方式登录，不是微信扫码。
旧 `qr` 和 `browser` 仍是遗留微信流程，不能据此承诺可用。
候选会话必须先通过对应协议的身份检查，才会与模式一起原子保存；失败不会替换原会话。

Web 签名由 Python 实现，不需要 Java、JAR 或 APK 资源。Web 离线 doctor 不执行签名或发现 Java。
离线测试和隔离安装测试使用合成响应，只证明本地实现与打包边界。
真实 Creator 登录、身份读回、图片上传、草稿、公开发布及清理仍需绑定最终候选产物逐项验收。
历史 `.7` 的发布和权属记录不能沿用为 `0.6.0rc1` 的放行依据。
