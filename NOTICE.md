# 权属与来源说明

## 许可证覆盖范围

本项目自有内容（`docs/`、`data/`、`scripts/`、`cli/` 源码、`signer/` 源码与根目录文档）采用 [MIT](LICENSE) 许可。

MIT 只覆盖本项目作者拥有的部分。它不覆盖目标应用的安装包、DEX、原生库或任何从原应用提取的资源，也不覆盖第三方组件。

## 不随仓库分发

研究样本、APK、签名器 JAR、账号数据与旧 Git 历史不在仓库或发布产物中，仓库也不包含任何从 APK 提取的资源。需要运行本地签名器时，使用者应自行取得官方安装包，并在本地提取和构建。

## README 封面素材

`docs/assets/cover-emoji.svg` 是 Twemoji 项目绘制的「眯眼吐舌」表情（U+1F61D）图形，原样收录，未作改动。

- 来源：[jdecked/twemoji](https://github.com/jdecked/twemoji) 仓库的 `assets/svg/1f61d.svg`（[原文链接](https://raw.githubusercontent.com/jdecked/twemoji/main/assets/svg/1f61d.svg)）。
- 许可：Creative Commons Attribution 4.0 International（[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)）。许可证文本由上游仓库的 `LICENSE-GRAPHICS` 提供。
- 署名：图形版权归 Twemoji 作者与贡献者所有。本项目未对其主张著作权，转载时需保留本段署名与许可说明。
- 校验和：`c5f4ca4764cc99f7630886806dbcc54a10d30337597bc0bf09f1ed548da676fd`。`scripts/check_repo.py` 固定该值，仓库内改动该文件会让离线检查失败。

该图片不在 MIT 许可范围内。仓库此前收录过目标应用安装包中的「开心」表情，因无法取得再分发许可已在公开发布前移除。

## 第三方组件

- Python 包没有任何运行时依赖，wheel 内不含第三方代码。
- `signer/` 依赖公开发布的 Unidbg（Apache-2.0）及其传递依赖，例如 unicorn、capstone、keystone、demumble、commons-codec、commons-collections4、commons-io、fastjson2、apk-parser、jna、native-lib-loader 与 slf4j。仓库不代管这些构件，使用者按各自许可证获取与使用。
- 使用者本地构建出的 `xhh-signer-loader.jar` 会把上述组件打进同一个 JAR。该产物不在本仓库的分发范围内，再分发它需要遵守各组件自己的许可证。

## 参考与免责

项目组织形式参考 [bilibili-API-collect](https://github.com/rinnein/bilibili-API-collect)，未复制其正文、图片、标识或许可证，也不代表获得对其他材料的再许可权。

本项目与目标平台没有关联，不代表平台授权，也不保证任何接口的长期可用性。使用者需要自行遵守平台服务条款与当地法律。本说明不是对平台服务条款的解释。
