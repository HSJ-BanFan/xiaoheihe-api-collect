# 首发验收范围

本页说明本地发布候选版验收了什么，以及哪些内容不能据此宣称可用。

## 候选版本

当前 Python CLI 候选版为 0.5.0rc4+standalone.7。验收分为三个互相独立的部分：本地包与签名器、线上功能、双账号隔离。

2026-10-08 的验收历史如下。run-24 使用 `.6` wheel 在门槛内构建签名器，通过 13 项本地检查，但报告仍列出 3 条 `not run` 事项且 live record 为 schema 1。run-26 用 schema 2 live record 重验，报告 `release_ready` 为 true。发布前复核发现 run-26 的 live record 绑定的是更早构建的 `.6` wheel，与当前源码构建出的 wheel 在包内 README 上有两段差异，因此该记录不覆盖拟发布的字节。

用 `.6` wheel 重跑线上验收时，第一步上传就返回 `status=failed`。上传分配接口探针显示，平台现在要求 `file_infos` 条目带 `width` 和 `height`，而客户端只在 Pillow 恰好可导入时才填这两个字段，所以干净安装下上传必然失败。`.7` 改为从 PNG、JPEG 或 GIF 字节读取尺寸，读不到时在本地给出明确错误，并补齐离线测试。

run-29 用 `.7` wheel 通过 12 项本地检查。run-30 在同样输入上加入绑定该 wheel 的 schema 2 live record 和 schema 2 权属记录，12 项本地检查全部通过，`open_items` 为空，`release_ready` 为 true。原始门槛报告、账号证据和线上日志留在本地研究案件中，不随公开仓库分发。项目尚未上传 GitHub。

| 部分 | 验收内容 | 结果 |
| --- | --- | --- |
| 本地包与签名器 | wheel 与源码及包内 README 一致，支持的 APK 可提取资源，用户构建的 loader 可复现参考签名 | 已通过本地门槛 |
| 线上功能 | 冷启动短信 App 登录、身份核对、账号读取、草稿、图片上传与读回、创作与互动操作及清理 | 已在授权测试账号上通过 |
| 双账号隔离 | 测试账号与主账号各自身份匹配、交叉身份不匹配、各自草稿读取成功 | 已由线上记录验证 |

现有线上记录没有设备标识断言。它证明账号身份与草稿读取互相隔离，不证明两账号使用了不同设备。门槛要求恰好两个不同别名；每个别名都要通过自身身份核对、拒绝另一身份，并读回自己的草稿。schema 2 记录和链接 JSON 的断言必须一致，链接文件必须位于记录目录内且 SHA-256 匹配。run-30 的两个别名是本次冷启动的测试账号与主账号。

## 登录结果

短信验证码流程是当前已验收的 App 登录方式。两种微信扫码流程都取得了 Web SSO 会话字段，但后续 App 与 Web 请求被平台要求重新登录。详见[登录与会话研究](research/authentication-and-signing.md)。

观察到一个副作用，同一账号重新登录后，旧别名 `personal` 的会话不再通过 `/account/info`，平台返回 `status=relogin`。这是观察结果，不构成对原因的结论。

## 发布内容

Python wheel 和 sdist 不含 APK、JAR、SO、账号库、手机号、验证码或浏览器配置。在线 App 请求需要用户自行取得受支持 APK、在本地准备签名器资源、构建 loader，并配置 Java 17 或更高版本。首次构建还需要 Git、Maven 和依赖下载。

MIT 许可覆盖本项目自有源码和文档。它不覆盖目标应用或第三方依赖。README 封面使用 Twemoji 的图形，按 CC BY 4.0 转载并署名，是目前仓库里唯一的非文本素材，校验和固定在 `scripts/check_repo.py`。许可边界见[权属与来源说明](../NOTICE.md)。

## 接口覆盖限制

接口目录有 448 条参考记录。243 条历史 GET 路径进入通用 call 白名单。接口目录数量和白名单成员都不代表逐条可用，也不保证 GET 没有副作用。

线上验收只覆盖[研究报告列出的功能](research/live-acceptance.md)。群聊、房间、搜索、部分社交和其他历史路径仍需分别研究和验收。

## 重跑本地门槛

在 cli 目录运行下列命令。APK、loader、live record 和 rights review 需要由操作者从本地受控位置提供。

~~~console
cd cli
python scripts/release_gate.py --wheel <candidate.whl> --apk <supported.apk> --loader <xhh-signer-loader.jar> --live-evidence <live-record.json> --rights-review <rights-review.json> --out <new-directory> --require-release-ready
~~~

门槛会在隔离 Python 环境中安装 wheel，核对 wheel 内源码，检查 APK，准备资源，安装并检查 signer bundle，运行离线签名自检，并在移动输入文件后再次签名。它不执行登录或线上业务请求。

live record 必须绑定 wheel、loader 和 APK 的 SHA-256。门槛还会检查最近 14 天的验收日期、六项功能读回、清理结果、两个账号断言以及链接证据 JSON 的 SHA-256。链接路径必须位于 live record 所在目录内。

权属记录为 schema 2，逐条列出仓库分发的每个素材及其路径、SHA-256、许可证、署名和可分发性，门槛会拿这份清单核对检出的文件，未登记的素材、被替换的字节和缺失的文件都会让权属记录失效。门槛另外比对 wheel 内嵌 README 与 `cli/README.md`，编辑打包文件后必须重新构建并重跑线上验收。

报告的 open_items 由本地检查、live record 和 rights review 的实际状态生成。任何阻塞项存在时，release_ready 都为 false。
