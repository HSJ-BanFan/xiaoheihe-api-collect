---
name: xiaoheihe-publisher
description: Use when 用户需要通过本地 CLI 登录小黑盒、上传自己的图片、保存服务端草稿、发布自己的帖子或核对发布结果。不用于他人内容批量互动；无需 MCP。
---

# 小黑盒创作与发布

本技能包含 `xhh-sdk 0.6.0rc1` 和受确认保护的发布入口。需要 Python 3.10+；Web 协议使用纯 Python 签名，不需要 Java/JAR；App 协议仍使用预编译签名器。协议由账号配置明确选择，失败时不自动换协议或账号。

脚本位置相对本文件。以当前 Python 执行 `scripts/xhh_cli.py` 或 `scripts/xhh_publish.py`，从任意工作目录均可使用。不要依赖全局安装的 `xhh-sdk`。缺少 `runtime/` 或完整性检查失败时，停止并取得完整发布包，不要跳过校验。

## 账号与签名器

首次配置或登录失败时先读 [setup.md](references/setup.md)。让用户明确选择账号别名；不要默认选择列表中的第一个账号。手机号、短信验证码、签名器、账号存储均留在用户机器上，不写入帖子 JSON、操作记录、报告或版本库。

Web 登录通过官方创作者页面完成。让用户点击登录，再用小黑盒 App 扫码或页面短信登录；不要把它称作微信扫码。

```console
python scripts/xhh_cli.py account add ALIAS --identity USER_NUMERIC_ID
python scripts/xhh_cli.py account login ALIAS --method creator --timeout 600 --confirm
python scripts/xhh_cli.py account status ALIAS --online
python scripts/xhh_cli.py --account ALIAS creator-options
```

只有身份核验通过后，Web 会话才会保存。旧 qr/browser 方法是另一套微信 SSO，不保证当前可用。Web 和 App 会话需要并存时使用不同别名。当前 Web 候选的线上验收状态以发行说明为准，不因有本地代码就宣称扫码或发帖已成功。

仅 App 模式需要以下安装。Windows x64 用户提供受支持 APK，并确认本地导入和签名测试后运行：

```console
python scripts/xhh_setup.py --apk USER.apk --install-java --confirm
python scripts/xhh_setup.py --apk USER.apk --account ALIAS --confirm
```

第一条仅配置签名器。缺少可用 Java 时，`--install-java` 允许下载私有 JRE，不改全局环境。第二条只绑定已存在的明确别名。`ready` 只代表本地固定向量匹配，不代表账号登录或线上发布成功。

完整 CLI 仍可直接使用：

```console
python scripts/xhh_cli.py --version
python scripts/xhh_cli.py account list
python scripts/xhh_cli.py account login ALIAS --method sms --phone USER_PHONE --confirm
python scripts/xhh_cli.py account status ALIAS --online
python scripts/xhh_cli.py --account ALIAS upload picture.png --confirm
```

短信登录可能需要先配置签名器及绑定用户自己的数字 ID，验证码阶段见 setup。现有会话通过检查不等于刚刚完成了新登录。

## 发布

先读 [publishing.md](references/publishing.md)，用其中的严格 JSON 格式准备内容。图片只接受本地 PNG/JPEG/GIF。相对路径按 JSON 所在目录解析。

```console
python scripts/xhh_publish.py plan post.json --account ALIAS --mode draft --out operation
python scripts/xhh_publish.py show operation
python scripts/xhh_publish.py submit operation --approval SHA256_FROM_SHOW --confirm
python scripts/xhh_publish.py reconcile operation
```

`plan` 只冻结待发内容与图片，不联系服务端。`draft` 写服务端草稿；`public` 才是公开发布意图。使用 `show` 展示已验证的完整内容、图片、别名、模式与 `approval_sha256`，在最后提交前获得用户对此快照的明确确认。内容变化时创建新计划并重新确认。

先用 `creator-options` 查询社区、标签、图文/文章计划和内容声明。`post_plan` 填服务端返回的 key，`extra_declaration` 填相应声明整数；没有实际选择时省略。不得为了通过提交擅自选择创作者计划。

只有 `submit` 才执行账号在线验证、真实上传和发帖。它调用 CLI upload 后，将图片作为带尺寸的内嵌 HTML 提交；早期 .7 的独立 images 块曾被服务端丢弃，图片发帖应使用此入口。不要在未确认时调用 CLI publish 绕过此流程。`attempt.json` 已存在时只能核对，不能删除它或换目录重发。超时或退出码 3 时先检查本人的帖子和草稿。正文核对可用 `scripts/xhh_cli.py --account ALIAS edit-info LINK_ID`，这不替代匿名可见性核验。

## 汇报结果

- `prepared`：仅有本地计划，尚未上传。
- `acknowledged`：服务端创建回执，不代表内容完整核对或公开可见。当前版本的读回结果保持此状态，并列出核对范围。
- `outcome_unknown`：可能已发生上传或发布，禁止自动重试。
- `refused`：请求未通过当前检查；不要把它描述成已发布。

只有有独立证据证明公开可见与内容一致才能声称公开发布已验证。当前 facade 不产生 `verified_public`，不以 `acknowledged` 触发成功日历或其他成功记账。对读取不到完整内容的草稿也不声称完整验证。
