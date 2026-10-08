# 权属与来源说明

## 许可证覆盖范围

本项目自有内容（`docs/`、`data/`、`scripts/`、`cli/` 源码、`signer/` 源码与根目录文档）采用 [MIT](LICENSE) 许可。

MIT 只覆盖本项目作者拥有的部分。它不覆盖目标应用的安装包、DEX、原生库或任何从原应用提取的资源，也不覆盖第三方组件。

## 不随仓库分发

研究样本、APK、签名器 JAR、账号数据与旧 Git 历史不在仓库或发布产物中。除 README 封面图片外，仓库不包含 APK 提取出的资源。需要运行本地签名器时，使用者应自行取得官方安装包，并在本地提取和构建。

## README 封面图片

`docs/assets/xhh-project-mascot.png` 使用小黑盒 App 安装包中的原版「开心」表情。源文件位于 `res/drawable-xxhdpi/expression_cube_kaixin.png`。封面图由 144 × 144 原图经 Lanczos 插值放大到 1152 × 1152，没有改绘。该图片不是本项目原创内容，也不在 MIT 许可范围内。相关权利归原权利人所有。使用或再分发该图片前，需取得权利人许可。

## 第三方组件

- Python 包没有任何运行时依赖，wheel 内不含第三方代码。
- `signer/` 依赖公开发布的 Unidbg（Apache-2.0）及其传递依赖，例如 unicorn、capstone、keystone、demumble、commons-codec、commons-collections4、commons-io、fastjson2、apk-parser、jna、native-lib-loader 与 slf4j。仓库不代管这些构件，使用者按各自许可证获取与使用。
- 使用者本地构建出的 `xhh-signer-loader.jar` 会把上述组件打进同一个 JAR。该产物不在本仓库的分发范围内，再分发它需要遵守各组件自己的许可证。

## 参考与免责

项目组织形式参考 [bilibili-API-collect](https://github.com/rinnein/bilibili-API-collect)，未复制其正文、图片、标识或许可证，也不代表获得对其他材料的再许可权。

本项目与目标平台没有关联，不代表平台授权，也不保证任何接口的长期可用性。使用者需要自行遵守平台服务条款与当地法律。本说明不是对平台服务条款的解释。
