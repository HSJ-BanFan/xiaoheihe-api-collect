<p align="center">
  <img src="docs/assets/chomper-weiqu-cover.png" width="300" alt="植物大战僵尸大嘴花咬住小黑盒委屈表情" />
</p>

<h1 align="center">小黑盒 API 收集与研究</h1>

<p align="center">
  <img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="MIT 许可" />
  <img src="https://img.shields.io/badge/python-%3E%3D3.10-blue.svg" alt="Python 3.10+" />
  <img src="https://img.shields.io/badge/routes-448-informational.svg" alt="参考记录数" />
  <img src="https://img.shields.io/badge/CLI-0.5.0rc4%2Bstandalone.7-informational.svg" alt="CLI 候选版本" />
  <a href="../../actions/workflows/offline-checks.yml"><img src="../../actions/workflows/offline-checks.yml/badge.svg" alt="离线检查" /></a>
</p>

<h3 align="center">社区维护的非官方接口参考</h3>
<h3 align="center">内容持续补充与修正</h3>

本项目对小黑盒 App 客户端接口做静态收集与整理，记录用途、参数线索和证据等级，并把可以复核的部分做成脱敏文档、数据快照和一套本地 CLI。研究方法包括 DEX 静态分析、字符串与调用点交叉引用、历史响应归档，以及受控的线上验收。

文档描述的是观察到的契约，不推断平台授权，也不保证接口长期可用。接口目录是参考资料，不是平台官方文档。

📖 阅读地址：[仓库内的参考目录](docs/README.md)。GitHub Pages 站点在仓库启用 Pages 后发布。

> **声明**
>
> 1. 本项目自有源码和文档采用 [MIT 许可](LICENSE)，第三方素材与平台资源不在其中，来源和边界见 [NOTICE](NOTICE.md)。
> 2. 本项目仅用于学习、研究与兼容性分析。请勿滥用，请勿用于违反平台条款或当地法律的用途。
> 3. 分享任何数据前请自行脱敏，不要提交账号、Cookie、手机号、验证码或原始响应。
> 4. 接口文档不代表平台授权，也不保证长期可用。使用本项目产生的后果由使用者承担。

## 🍴目录

详细分类、参数线索和历史证据见[参考目录](docs/README.md)。

| 业务 | 参考记录数 | 业务 | 参考记录数 |
|---|---:|---|---:|
| [账号与设置](docs/account/README.md) | 47 | [社区与创作](docs/community/README.md) | 45 |
| [个人资料与社交](docs/profile/README.md) | 19 | [游戏数据](docs/games/README.md) | 74 |
| [商城与商店](docs/mall/README.md) | 38 | [搜索](docs/search/README.md) | 21 |
| [消息与通知](docs/notifications/README.md) | 9 | [系统与其他](docs/system/README.md) | 6 |
| [任务状态](docs/tasks/README.md) | 4 | [调试与测试](docs/debug/README.md) | 3 |
| [百科](docs/wiki/README.md) | 3 | [群聊与语音社群](docs/groups/README.md) | 167 |
| [登录与会话](docs/login/README.md) | 6 | [图片与对象上传](docs/upload/README.md) | 6 |

研究报告：

- [接口目录范围](docs/research/api-inventory.md)：记录构成、证据等级和调用限制。
- [登录与签名](docs/research/authentication-and-signing.md)：App、Web 会话及签名器运行边界。
- [线上验收](docs/research/live-acceptance.md)：已验证功能和未验证范围。
- [首发验收记录](docs/first-release-gate.md)：候选版门槛、结果和重跑命令。

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

当前候选版本为 `xhh-sdk 0.5.0rc4+standalone.7`。run-40 用该 wheel 通过 12 项本地检查，绑定的线上验收记录和 schema 2 权属记录都有效，开放项为空，`release_ready` 为 true。发布产物位于 `cli/dist/standalone-7-clean`，wheel 的 SHA-256 为 `2ca9af8ece4e105631e62c6c4043e1fa758c766e16031afd4e52028bc44293ff`。

## 🌱参与贡献

欢迎提交接口补充、文档纠错和失效上报。开始前请阅读 [贡献指南](CONTRIBUTING.md)：

- 只提交有证据支持的字段，并区分观察事实、分析推断和未验证事项。
- 不要提交账号库、凭据、原始响应、设备实值、绝对宿主路径或应用安装包。
- 改动生成文档后运行 `python scripts/generate_reference.py`，再运行 `python scripts/check_repo.py` 和 `python -m unittest discover -s tests -v`。

## 许可与使用边界

项目自有源码和文档采用 [MIT 许可](LICENSE)。README 与文档站的封面是 2026-10-08 为本仓库生成的图像，参考了小黑盒 App 的本地表情素材和[植物大战僵尸 Wiki](https://plantsvszombies.wiki.gg/wiki/File:Chomper-hd.png) 的大嘴花图；原始参考文件没有随仓库分发，仓库所有者已批准公开显示该封面。相关角色和素材的权利仍归各自权利人，封面不在 MIT 许可范围内，也没有单独的复用许可。仓库另保留两份按 CC BY 4.0 分发的 Twemoji 相关 SVG。平台商标、用户提取的应用资源和第三方依赖同样不在 MIT 范围内。仓库不分发任何从目标应用提取的资源。使用者需要遵守平台条款和当地法律；接口文档不代表平台授权，也不保证接口长期可用。完整说明见 [NOTICE](NOTICE.md) 和 [安全说明](SECURITY.md)。
