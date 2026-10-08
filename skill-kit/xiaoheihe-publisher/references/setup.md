# 本地设置与真实登录

完整发布目录必须同时保留 SKILL、scripts、references、LICENSE、runtime 和 kit-manifest.json。Python 3.10+ 即可离线规划，不需要 pip 安装 SDK。在线签名需要用户自己准备 Java 17+ 和合法取得、核对过的签名器。此包不包含 APK、JAR、SO、账号、浏览器资料或默认账号。

## 查看当前能力

```console
python scripts/xhh_cli.py --help
python scripts/xhh_cli.py account --help
python scripts/xhh_cli.py signer --help
python scripts/xhh_cli.py account list
```

原版账号管理使用 Windows DPAPI，账号默认保存在用户主目录 `.xhh_sdk` 下。本 facade 不读取密文、不改变存储格式、不支持指定另一个账号目录。跨平台离线 plan/show 可用；其他系统上的原版账号登录受原 CLI 限制。

## 配置用户自备签名器

用户先检查 JAR 来源并明确选择 SHA-256。哈希只固定字节，不证明程序安全。下列本地变更也需要确认。

```console
python scripts/xhh_cli.py signer install USER_SIGNER.jar --sha256 TRUSTED_SHA256 --confirm
python scripts/xhh_cli.py account add ALIAS --identity USER_NUMERIC_ID
python scripts/xhh_cli.py account configure ALIAS --set signer_jar=managed:TRUSTED_SHA256 --confirm
python scripts/xhh_cli.py --account ALIAS doctor --offline
```

账号已存在时跳过 add，先核对别名。从源码构建 loader 的步骤见[签名器说明](https://github.com/HSJ-BanFan/xiaoheihe-api-collect/blob/main/signer/README.md)。用自己的受支持 APK 准备资源后安装：

```console
python scripts/xhh_cli.py signer prepare-apk USER_APK.apk --out USER_RESOURCES --confirm
python scripts/xhh_cli.py signer bundle-install --resources USER_RESOURCES --loader USER_LOADER.jar --loader-sha256 TRUSTED_SHA256 --confirm
python scripts/xhh_cli.py account configure ALIAS --set signer_bundle=bundle:RETURNED_BUNDLE_SHA256 --confirm
```

`bundle:` 引用使用 signer_bundle，不是 signer_jar。受支持 APK 和 loader 由用户本地持有，不随此包分发。

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
