# 权属与来源说明

## 许可证覆盖范围

本项目自有内容（`docs/`、`data/`、`scripts/`、`cli/` 源码、`signer/` 源码与根目录文档）采用 [MIT](LICENSE) 许可。

MIT 只覆盖本项目作者拥有的部分。它不覆盖目标应用的安装包、DEX、原生库或任何从原应用提取的资源，也不覆盖第三方组件。

## 不随仓库分发

研究样本、APK、提取资源、账号数据与旧 Git 历史不在仓库或发布产物中。使用者自行取得受支持安装包，设置器只在本机提取必要资源。预编译 bootstrap JAR 可作为单独 release 资产发布，Git 源码和技能 ZIP 不含 JAR。它只包含项目自有代码、选定的第三方 Java 源码编译结果及相应许可说明，不包含目标 APK、目标 SO、第三方原生文件或依赖 JAR。

## README 封面素材

`docs/assets/chomper-weiqu-cover.png` 是当前 README 和文档站的封面图。该图于 2026-10-08 通过 Magpie 的 `codex/gpt-image-2.5` 生成。参考素材是本地 `case-2026-apk01` 研究工作区解包得到的小黑盒 App `expression_cube_weiqu.png` 表情，以及[植物大战僵尸 Wiki 上的 Chomper-hd.png](https://plantsvszombies.wiki.gg/wiki/File:Chomper-hd.png)。原始参考文件没有放入仓库。封面图的 SHA-256 为 `5bbfb77b4c2a26004879c1e1fbb76f6c6d98819f25e6027fe2a257c078a49071`。

仓库所有者已批准在本仓库公开展示这张生成图。小黑盒和植物大战僵尸角色的权利仍归各自权利人所有。该批准不转让相关权利，也不授予其他人单独复用这张图的许可。此生成图不在 MIT 许可范围内。本说明记录仓库所有者的决定和参考来源，不表示任何权利人授予了许可。

仓库还保留两份旧素材，其中一份用于文档站图标：

- `docs/assets/emoji-cry.svg` 是 Twemoji 的 U+1F62D 图形，原样收录自 [jdecked/twemoji](https://github.com/jdecked/twemoji/blob/main/assets/svg/1f62d.svg)，用作文档站 favicon。SHA-256 为 `d0333b5cb416ad6545055766fc8128566874ab5ead272e5a691a24704048f077`。
- `docs/assets/logo.svg` 是旧版自绘大嘴花插画，其中包含 Twemoji 图形。SHA-256 为 `8a0e29cff18a957a20f01d11d3b93738e01ada093e8286b60962068fa9d3aa22`。

Twemoji 图形采用 Creative Commons Attribution 4.0 International（[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)）许可。复用时请保留署名和许可说明。旧版 SVG 标识由 CC BY 4.0 的 Twemoji 图形与项目自绘插画组成，因此整份 SVG 按 CC BY 4.0 分发。

## 第三方组件

- Python 包没有任何运行时依赖，wheel 内不含第三方代码。
- `signer/` 依赖公开发布的 Unidbg（Apache-2.0）及其传递依赖，例如 unicorn、capstone、keystone、demumble、commons-codec、commons-collections4、commons-io、fastjson2、apk-parser、jna、native-lib-loader 与 slf4j。仓库不代管这些构件，使用者按各自许可证获取与使用。
- 使用者本地构建出的 `xhh-signer-loader.jar` 会把上述组件打进同一个 JAR。该产物不在本仓库的分发范围内，再分发它需要遵守各组件自己的许可证。
- 新的 `xhh-signer-bootstrap-0.2.0.jar` 不使用旧 fat-JAR 分发方式。其选定源码、修改、许可和上游获取边界见 [signer/THIRD-PARTY.md](signer/THIRD-PARTY.md)。设置器直接从上游下载锁定字节，在本机组装资源 JAR；本项目不重新发布该资源 JAR、依赖或 JRE。

## 参考与免责

项目组织形式参考 [bilibili-API-collect](https://github.com/rinnein/bilibili-API-collect)，未复制其正文、图片、标识或许可证，也不代表获得对其他材料的再许可权。

本项目与目标平台没有关联，不代表平台授权，也不保证任何接口的长期可用性。使用者需要自行遵守平台服务条款与当地法律。本说明不是对平台服务条款的解释。
