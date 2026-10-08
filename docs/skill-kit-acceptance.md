# AI 发布包验收记录

2026-10-08 对 `xhh-publisher-kit 0.1.0rc1` 和 Easel `master` 的小黑盒 Skill 进行了独立离线检查及测试账号实测。

## 固定产物

| 对象 | 版本或 SHA-256 |
| --- | --- |
| Kit 源码提交 | `f986a21fd6e58cb2357b6ece10908eabb2e49796` |
| Kit ZIP | `38ed57713febff677d000cdc1c2fea09cf16c6e1707ac047f9c4337d52965628` |
| Kit manifest | `2cecef3176cf36ce3e5f77ccf0eccc135892558d917b1a3d90cbd6cd28ea5c82` |
| 原 CLI | `0.5.0rc4+standalone.7` |
| 原 CLI wheel | `2ca9af8ece4e105631e62c6c4043e1fa758c766e16031afd4e52028bc44293ff` |

25 个 CLI wheel 成员逐字节保留。Kit 和 Easel 不携带 JAR、APK、SO、账号库或真实凭据。两次独立构建产生相同 ZIP。技能可复制到其他目录后使用，不依赖研究工作台或全局 `xhh-sdk`。

## 本轮结果

| 检查 | 结果 |
| --- | --- |
| Kit 离线回归 | 52 项通过，含真实子进程、中文和 emoji、冻结图片、完整性、确认和重复提交保护 |
| 仓库测试 | 72 项通过 |
| 原 CLI 测试 | 458 项通过，存在已有的重复 ZIP 成员告警 |
| 显式账号与 App 会话 | 测试账号现有会话通过签名在线身份核验 |
| 图片上传 | 真实 CDN 上传通过；独立上传原始对象与本地 PNG 字节相同 |
| 服务器草稿 | 创建、列表读回、删除并确认消失 |
| Easel 公开模式图文 | 通过 Easel 包装器提交，服务端完整正文保留中文、emoji 和内嵌图片 |
| 图片持久化 | 编辑读回包含图片块；CDN 图片为 640×360，目视核对为测试图 |
| 其他账号可见 | 另一个账号只读访问成功，标题和正文摘要一致 |
| 清理 | 本轮创建的帖子和草稿均已删除，并从本人列表确认消失 |

图片预览由平台转换为 WebP，不能用预览文件与原始 PNG 的 SHA-256 不同判定上传损坏。图片尺寸和视觉内容已另行核验。此记录不包含账号别名、手机号、帖子 ID、临时 CDN URL 或原始响应。

## 验收中修复的问题

1. Windows 隔离 Python 子进程默认用 GBK 读取标准输入，可能改写确认过的中文。两个启动入口现在固定 UTF-8，中文和 emoji 通过真实子进程回归。
2. 原版 CLI 的独立图片块与 HTML 正文组合时，服务端曾接受创建却丢弃图片。Kit 现在先用原 CLI 上传，再将 URL 和尺寸嵌入 HTML，最后用原 CLI 发帖。服务端已实测保留图片，原 wheel 不修改。
3. Easel 的 HTML 内容检查增加实际可见文本和摘要检查，避免 HTML 实体或标签拆分掩盖敏感文本。文档 JSON 示例由真实 CLI 执行测试保护。

## 未验证与限制

- 本轮复用了有效 App 会话，没有重新发送短信或换取新会话。短信登录入口和依赖仍完整保留，旧 CLI 的新登录证据不能冒充本轮结果。
- 未登录网页触发平台 CAPTCHA，未绕过验证，未证明匿名公众可见。其他已登录账号可见已单独实测。
- 创建回执保持 `acknowledged`；自动 reconcile 只做有限列表核对，不伪造完整验证状态。
- 本机 OpenClaw 模型服务返回 HTTP 401，真实模型自主执行链未通过。独立 AI 消费者实际完成 Skill 离线计划与核对，Easel 包装器真实图文发帖已单独实测。
- Easel 全量 Windows 本地测试存在 21 项与修改前一致的失败；新增集成测试通过，不宣称全库本地全绿。
- 支持的 API 没有上传对象删除入口。测试帖子已清理，上传的 CDN 对象可能继续存在；不宣称零残留。
- 托管账号依赖 Windows DPAPI；Java 与签名器由用户本地提供。

这是带明确范围的预发布验收，不修改原 CLI 发布门槛，也不承诺平台接口长期可用。
# Precompiled setup follow-up

The 0.2.0rc1 kit adds precompiled setup without modifying the original
0.5.0rc4+standalone.7 wheel. The focused bootstrap, builder, setup and kit
tests passed locally. The full repository test run passed 107 tests before
the final notice-only rebuild; release review must rerun it on the final
source state.

A real local run used the supported user APK and exact upstream artifact
fixtures, a clean Java search path, a privately extracted Temurin JRE 17,
and Chinese, space and plus-sign directory names. It assembled the local
resource JAR, installed the immutable dependency graph and matched the
synthetic /account/info vector at timestamp 1700000000. No user account,
login, upload or publishing API was accessed. Cached-fixture acceptance is
separate from a fresh public-release HTTP download and does not establish
that the final release has been published.

The earlier publishing evidence below belongs to the earlier kit and its
specific tested artifact. It is not new online acceptance for 0.2.0rc1.

