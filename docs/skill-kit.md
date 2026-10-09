# AI 发布技能包

`xhh-publisher-kit 0.2.0rc1` 是独立版本的发布入口，不是新 SDK wheel。
构建器固定原 `xhh-sdk 0.5.0rc4+standalone.7` 的 wheel SHA-256：
`2ca9af8ece4e105631e62c6c4043e1fa758c766e16031afd4e52028bc44293ff`。
旧 wheel 的验收不代表新发布入口已经完成线上验收。

发布页为 [0.2.0rc1 技能包](https://github.com/HSJ-BanFan/xiaoheihe-api-collect/releases/tag/skill-kit-v0.2.0rc1)。
完整结果见[本轮验收记录](skill-kit-acceptance.md)，其中区分真实图文发帖、现有会话、新登录和模型执行结果。

解压后将完整的 `xiaoheihe-publisher/` 放到所用 Agent 的技能目录，例如 `~/.agents/skills/`。
保留 runtime 和 manifest，不要只复制 SKILL.md。Easel 使用仓库内集成版本，不需要另行安装全局 CLI。

普通用户使用完整技能 ZIP。单独的 `.7` wheel 是保留不变的底层 CLI，不包含新增设置入口。其构建说明面向维护者，不是完整工具包的安装步骤。

## 其他项目如何接入

下载并核对 Release 的 `SHA256SUMS`，保留完整工具包作为固定版本依赖。接入项目只负责命令参数、用户确认和 JSON 结果处理：

- `scripts/xhh_setup.py` 安装本地签名运行环境；`state=ready` 和 `selftest.matched=true` 表示本地签名通过。
- `scripts/xhh_cli.py` 管理用户自己的账号并执行登录、查询、独立上传等命令。
- `scripts/xhh_publish.py` 提供 plan、show、submit、reconcile。服务器草稿和公开发帖都由 submit 写入，未知结果不重发。

无需复制 `signer/` 构建工程、研究数据或维护者账号。Easel 的同步脚本只校验并更新工具包快照，运行时仍调用同一套上游命令。安装器目前支持 Windows x64 与固定 APK profile，不能把它解释为任意 APK 或跨平台原生运行支持。

## 离线构建

在仓库根目录运行。输出目录必须不存在。

```console
python scripts/build_skill_kit.py --wheel cli/dist/standalone-7-clean/xhh_sdk-0.5.0rc4+standalone.7-py3-none-any.whl --out cli/dist/skill-kit-local
```

输出为展开的 `xiaoheihe-publisher/`、`xhh-publisher-kit-0.2.0rc1.zip` 和 `SHA256SUMS`。
构建只复制九个明确列出的技能源码文件及 25 个原 wheel 成员。
kit-manifest.json 记录每个文件哈希及 SDK、kit 版本和输入 wheel 哈希。
ZIP 固定顺序、时间、文件权限并使用无压缩条目，同样输入产生相同字节。
构建器不下载资源，不包含主仓库图片、账号、签名器或私有资源。

## 使用

解压后保留完整目录。技能入口见 [SKILL.md](../skill-kit/xiaoheihe-publisher/SKILL.md)，
真实登录和签名器配置见 [setup.md](../skill-kit/xiaoheihe-publisher/references/setup.md)。

```console
python KIT/scripts/xhh_cli.py --version
python KIT/scripts/xhh_setup.py --apk USER.apk --install-java --confirm
python KIT/scripts/xhh_setup.py --apk USER.apk --account ALIAS --confirm
python KIT/scripts/xhh_cli.py account list
python KIT/scripts/xhh_cli.py account login ALIAS --method sms --phone USER_PHONE --confirm
python KIT/scripts/xhh_cli.py --account ALIAS upload picture.png --confirm
python KIT/scripts/xhh_publish.py plan post.json --account ALIAS --mode draft --out operation
python KIT/scripts/xhh_publish.py show operation
python KIT/scripts/xhh_publish.py submit operation --approval APPROVED_SHA256 --confirm
python KIT/scripts/xhh_publish.py reconcile operation
```

KIT 代表展开的技能目录。提交前必须审阅 show 输出并确认账号、模式、内容、图片和摘要。
公开发帖在 plan 阶段选择 `--mode public`。不能通过修改 JSON 或省略确认扩大操作范围。

Windows x64 的首次设置不需要用户编译 Java。`--install-java` 只在找不到合适运行时时允许下载私有 JRE；程序不修改全局环境。APK 先经完整哈希核对，全部依赖与资源以内置固定锁验证。只在本地真实签名参考向量匹配后才绑定明确的现有账号。`ready` 不表示已登录或发布。签名器说明见 [signer/README.md](../signer/README.md)。

原版完整 CLI 没有删减，登录、签名器管理、独立上传和专门操作均可调用。
facade 只接受已冻结的本地图片，不代管凭据，也不重建远端协议。
API 与错误码见 [publishing.md](../skill-kit/xiaoheihe-publisher/references/publishing.md)。

图片提交经过 kit 适配：保留单次尝试记录后，调用原版 upload，检查返回的 HTTPS CDN URL 和尺寸，
使用原版文本渲染结果追加带尺寸的内嵌 HTML img，再调用原版 publish，images=[]。
原版 .7 的独立 images 块在实测中可能被服务端丢弃；其代码保持不变，AI 图片发帖使用 facade。

## 验证和限制

```console
python -m pytest tests/test_skill_kit.py -q
python scripts/check_repo.py
```

测试实际构建包、移动后从无关目录执行原 CLI/plan/show、固定运行时字节、拒绝未知成员和篡改、
严格规格、冻结图片、确认摘要、账号在线预检、单次尝试并发保护、发布参数、超时与回执失败。
在线传输使用合成测试替身；这些测试不会读取真实账号、运行签名器或访问平台。

创建回执是 acknowledged，不是公开可见性验证。当前 readback 只核对本人列表的已知字段，
始终保留 full_content_verified=false 和 public_visibility_verified=false。
当前 facade 不输出 verified_draft/verified_public，也不在未知结果后自动重试。

离线计划跨平台可用。原版账号存储依赖 Windows DPAPI；本包不实现跨平台账号迁移。
多个外部进程同时修改账号不受本包锁保护。manifest 用于完整性检测，不是防恶意替换包的签名。
操作目录含用户自己的待发内容，不得打入发布包或提交到版本库。
