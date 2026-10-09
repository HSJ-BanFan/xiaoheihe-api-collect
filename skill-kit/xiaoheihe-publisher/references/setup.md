# 本地设置与真实登录

完整发布目录必须同时保留 SKILL、scripts、references、LICENSE、runtime 和 kit-manifest.json。Python 3.10+ 即可离线规划，不需要 pip 安装 SDK。Web 模式不使用 Java/JAR；App 签名器设置支持 Windows x64，不需要 JDK、Maven 或 Git。此技能 ZIP 不包含 APK、JAR、SO、账号或浏览器资料。

## Web 登录

本包使用 `xhh-sdk 0.6.0rc1`。安装可选浏览器依赖后，Edge/Chrome 使用已有浏览器；选择 chromium 时另行运行 `python -m playwright install chromium`。

```console
python -m pip install "playwright>=1.50,<2"
python scripts/xhh_cli.py account add ALIAS --identity USER_NUMERIC_ID
python scripts/xhh_cli.py account login ALIAS --method creator --browser msedge --timeout 600 --confirm
python scripts/xhh_cli.py account status ALIAS --online
python scripts/xhh_cli.py --account ALIAS doctor --offline
python scripts/xhh_cli.py --account ALIAS creator-options
```

用户在官方创作者页面点击登录，再用小黑盒 App 扫码或页面短信登录。这个二维码不是微信二维码。登录在新的临时浏览器会话进行，不读取个人浏览器配置。候选会话以 Web 协议核对身份，通过才按账号修订号保存凭据和 `protocol_mode=web`，失败保留原配置。窗口超时不表示登录成功。

账号库由当前 Windows 用户 DPAPI 加密。需要并存 App 与 Web 会话时创建两个别名。`--protocol app` 或 `--protocol web` 只覆盖本次命令，不改存储，也不能把一种会话转换成另一种。旧账号默认 App。鉴权失败不自动换协议重发。

Web 账号无需下面的 APK 安装。App-only 群聊不支持 Web 模式。当前候选 Web 线上验收仍以发行说明为准，本地测试不等于真实登录发帖通过。

## 查看当前能力

```console
python scripts/xhh_cli.py --help
python scripts/xhh_cli.py account --help
python scripts/xhh_cli.py signer --help
python scripts/xhh_cli.py account list
```

原版账号管理使用 Windows DPAPI，账号默认保存在用户主目录 `.xhh_sdk` 下。设置器的 `--data-dir` 与原 CLI 的同名参数指定同一个账号目录，发布 facade 不支持另一个账号目录。若设置时使用自定义目录，后续使用原 CLI 时必须继续显式传入它，不要假定 facade 也会切换目录。跨平台离线 plan/show 可用。

## 一条命令导入 APK

用户提供合法取得的受支持 APK。程序先验证整个 APK，再下载固定版本依赖。不会上传 APK，不登录、不发短信、不发布内容。

```console
python scripts/xhh_setup.py --apk USER.apk --confirm
python scripts/xhh_setup.py --apk USER.apk --install-java --confirm
python scripts/xhh_setup.py --apk USER.apk --java JAVA_EXECUTABLE --account ALIAS --confirm
```

第一条要求已有 Java 17+ x64。若输出 `java_missing`，第二条明确授权程序按内置哈希下载 Temurin JRE 17。JRE 只保存在私有缓存，不写注册表，不修改 PATH 或 JAVA_HOME。`--java` 显式指定的运行时不合适时直接拒绝。

默认安装仅返回 `bundle:` 引用。`--account ALIAS` 只在真实本地签名与固定参考向量匹配后，修改该现有账号的 `signer_bundle` 和 `java`。未知别名不会创建，不会选择默认账号；其他设备参数、会话和账号保持原值。不要同时为同一别名运行设置和登录。

首次设置约下载 165 MB，包括可选 JRE。上游依赖由发布者提供；原生资源在本机组装，不由本项目重新发布。所有下载都核对字节数和 SHA-256，修改过的缓存拒绝使用而非覆盖。默认缓存为 `~/.xhh_sdk/setup-cache`，可通过绝对路径 `XHH_SETUP_HOME` 指定；bundle 继续遵循原版 `XHH_BUNDLE_HOME`。这些目录不含默认账号。

```console
python scripts/xhh_setup.py --apk USER.apk --offline --confirm
python scripts/xhh_cli.py account add ALIAS --identity USER_NUMERIC_ID
python scripts/xhh_setup.py --apk USER.apk --account ALIAS --offline --confirm
```

再次设置仍需 APK，`--offline` 只使用已核验缓存，每次重跑实际签名测试。安装完成后，日常签名不再需要原 APK、源码目录或网络下载。已安装 bundle 在每次签名时重新核对资源、loader 和依赖。旧 bundle 不自动删除。

`ready` 与 `selftest.matched=true` 仅证明当前受支持配置可执行本地签名，不证明登录、网络接口或公开可见。错误不会回显账号凭据。`account_binding_failed` 可保留已测试 bundle，修复明确别名后重试；不要删改账号存储来修复依赖。

自行维护源码构建者可读[签名器说明](https://github.com/HSJ-BanFan/xiaoheihe-api-collect/blob/main/signer/README.md)。原版 CLI 的 prepare-apk、bundle-install 与 signer install 仍保留，`bundle:` 绑定键是 signer_bundle，不是 signer_jar。

## 短信登录

由用户提供手机号并确认发送短信。未绑定的别名需要 `--identity USER_NUMERIC_ID`。原 CLI 使用已配置签名器完成真实请求。

短信流程还需要设备风控 token。若账号尚未保存 token，先安装可选 Playwright 并运行 risk-token，引导用户在自己的浏览器登录以获取 token。这个 token 不等于 App 登录会话，App 会话仍由短信验证码换取。已有有效 token 时跳过此步。

```console
python -m pip install "playwright>=1.50,<2"
python -m playwright install chromium
python scripts/xhh_cli.py account risk-token ALIAS --browser chromium --confirm
```

```console
python scripts/xhh_cli.py account login ALIAS --method sms --phone USER_PHONE --confirm
python scripts/xhh_cli.py account login ALIAS --method sms --phone USER_PHONE --code USER_CODE --confirm
python scripts/xhh_cli.py account status ALIAS --online
```

验证码是一次性的，只用于用户本次登录。不要记录命令中实际号码或验证码，不要把它们发到仓库、报告、截图或讨论中。本包不会自动安装浏览器，也不复制浏览器凭据。

QR/browser 登录入口仍保留，但原 CLI 的历史验证中 Web 会话可能不被 App API 接受。判断当前会话可用性必须看 `account status ALIAS --online` 的 `state=verified`、`api_identity_verified=true`、`session_valid=true`，不能把弹出的登录页当成成功。

## 独立上传与读回

先展示将上传的图片和别名，确认后执行：

```console
python scripts/xhh_cli.py --account ALIAS upload picture.png --confirm
python scripts/xhh_cli.py --account ALIAS drafts
python scripts/xhh_cli.py --account ALIAS posts
python scripts/xhh_cli.py --account ALIAS read LINK_ID
```

原版 CLI 输出可能含账号自己的内容；共享前脱敏。facade 不回显原版 stderr 或原始请求内容。账号在在线验证与提交之间若被其他进程修改，当前包不能提供跨进程身份锁；提交期间不要改动账号配置。
