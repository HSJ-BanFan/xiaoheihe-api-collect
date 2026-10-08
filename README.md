<p align="center">
  <img src="docs/assets/cover-emoji.svg" width="180" alt="封面：Twemoji 眯眼吐舌表情" />
</p>

<h1 align="center">小黑盒 API 收集与研究</h1>

<p align="center">小黑盒 App API 参考、脱敏研究报告与配套 Python CLI</p>

<p align="center">社区维护的非官方项目</p>

本地候选版本为 `xhh-sdk 0.5.0rc4+standalone.6`。run-26 已通过本地发布门槛，复核了 12 项检查、双账号记录和权属记录，开放项为空。复核没有重复执行线上登录或写操作。项目尚无 GitHub Release。详情见[首发验收记录](docs/first-release-gate.md)。

## 项目内容

| 路径 | 内容 |
| --- | --- |
| [`docs/`](docs/README.md) | 按业务分组的接口参考、认证说明、证据口径和研究报告 |
| [`data/`](data/) | 脱敏后的接口快照，是参考目录的公开数据源 |
| [`cli/`](cli/README.md) | 用于离线查阅和部分受控操作的 Python CLI |
| [`signer/`](signer/README.md) | 在用户本机从源码构建 App 请求签名器的 Java loader |

## 离线查看接口

需要 Python 3.10 或更高版本。在仓库根目录运行：

```console
cd cli
python -m xhh_sdk.cli catalog
python -m xhh_sdk.cli catalog --search /account/info --json
python -m xhh_sdk.cli --help
```

离线目录和帮助不需要账号、网络、Java 或签名器。安装方式、命令清单和账号配置见 [CLI 使用说明](cli/README.md)。

## 在线调用需要本地运行环境

App 签名请求需要你自己的登录凭据、受支持 APK 提取出的资源、本地构建的 signer JAR，以及 Java 17 或更高版本。首次构建还需要 Git、Maven 和依赖下载。详细步骤见[签名器说明](signer/README.md)和[受支持 APK](docs/supported-apk.md)。

仓库和 Python 包不包含 APK、JAR、SO、账号库、真实凭据或浏览器配置。项目自有签名器源码位于 `signer/`。本地构建出的 JAR 和提取资源由用户自行保管。

目前通过线上验收的 App 登录方式是短信验证码。两种已测试的微信扫码流程只得到 Web SSO 会话；平台对这些会话发出的 App 与 Web 请求均返回重新登录状态。详见[登录与会话](docs/login.md)。

## 接口范围与验收状态

接口快照有 448 条参考记录，其中 445 条是固定路径，另有 3 条辅助请求或模板。243 条历史 GET 路径进入通用 `call` 白名单。接口数量和白名单都不代表逐条线上可用，也不保证 GET 请求没有副作用。

线上验收只覆盖经过授权的部分流程：短信 App 登录和身份核对、账号与草稿读取、图片上传和字节读回、草稿创建与删除、选定的发布和互动操作及清理，以及两个账号的身份和草稿隔离。其他路径仍需分别研究和验收。逐项结果见[线上验收报告](docs/research/live-acceptance.md)。

## 阅读研究报告

- [接口目录范围](docs/research/api-inventory.md)：记录构成、证据等级和调用限制。
- [登录与签名](docs/research/authentication-and-signing.md)：App、Web 会话及签名器运行边界。
- [线上验收](docs/research/live-acceptance.md)：已验证功能和未验证范围。
- [首发验收记录](docs/first-release-gate.md)：候选版门槛、结果和重跑命令。
- [权属与来源说明](NOTICE.md)：MIT 许可范围、第三方组件与不随仓库分发的材料。

## 许可与使用边界

项目自有源码和文档采用 [MIT 许可](LICENSE)。README 封面使用 Twemoji 的「眯眼吐舌」表情图形，按 CC BY 4.0 转载，不在 MIT 许可范围内；平台商标、用户提取的应用资源和第三方依赖同样不在 MIT 范围内。仓库不分发任何从目标应用提取的资源。使用者需要遵守平台条款和当地法律；接口文档不代表平台授权，也不保证接口长期可用。完整说明见 [NOTICE](NOTICE.md) 和 [安全说明](SECURITY.md)。
