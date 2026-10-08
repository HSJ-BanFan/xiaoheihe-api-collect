# CLI 附录

[返回 API 目录](README.md) · [CLI 安装与使用](../cli/README.md) · [发布前检查](../cli/RELEASE.md)

## 离线查目录

CLI 位于 `cli/`，Python 包位于 `cli/xhh_sdk/`。从项目根目录安装后可查看帮助和本地目录。安装依赖可能需要软件包网络，下面的目录命令本身不请求小黑盒。

```console
python -m pip install ./cli
xhh-sdk --help
xhh-sdk catalog --route /account/info --json
xhh-sdk catalog --group --json
```

日常使用普通安装或已构建的 wheel，不使用 `pip install -e`。可编辑安装直接引用源码路径，移动源码会使它失效。普通安装将代码复制到 Python 环境中；Python 环境本身仍需保持原位置。

## 独立运行依赖

用户提供的签名器只导入用户目录，不放入公开源码或 wheel。

```console
xhh-sdk signer install <local-signer.jar> --sha256 <trusted-sha256> --confirm
xhh-sdk account configure <alias> --set signer_jar=managed:<sha256> --confirm
xhh-sdk signer inspect managed:<sha256>
xhh-sdk --account <alias> doctor --offline
```

`managed:<sha256>` 引用默认解析到用户目录 `.xhh_sdk/signers/<sha256>.jar`。`XHH_SIGNER_HOME` 可以显式指定绝对存储目录，`--data-dir` 仅选择账号库。安装和检查不会执行 Java、登录或发请求。摘要表示字节一致，不表示签名器来源可信或安全。

显式配置的失效路径不会自动回退到另一个 JAR。迁移旧配置时应明确选择导入后的引用。相对文件路径和自定义绝对文件路径仍属于依赖位置的兼容方式，不获得 managed 引用的移动保证。

签名器按需初始化。缺少 JAR 或 Java 不阻止本地目录与 unsigned Web/COS 请求构造；需要 App 签名的请求仍会拒绝执行。网页上传需要有效凭据和用户确认，离线测试通过不代表线上上传通过。

公开文档包含源码与登录补充路径，CLI 目录保留原有三组目录结构，因此两份 JSON 的总记录数不必相同。243 条白名单、167 条群目录和 9 条待复核路径集合必须一致。

## 通用调用边界

通用 `call` 只允许 243 条白名单 GET。在线调用需要自行授权的账号、必要运行依赖及事先核实的参数。命令的形态是 `xhh-sdk --account <alias> call <allowlisted-route>`。

文档不对非白名单路径生成通用调用示例，也不提供批量调用脚本。`group list`、`group members` 与 `group messages` 是独立的具名读取入口。群成员与消息读取需遵循账号所属群门禁。

## 写操作与登录

上传、草稿、发帖、评论、收藏、关注、删除、短信发送和登录授权均不是离线目录查询。它们可能修改外部状态，不能为了验证文档而自动运行。

具名命令入口的存在、历史成功记录和本轮离线测试是不同证据。参数与确认行为以 CLI 自带帮助和实现为准。

候选版的线上验收范围见[脱敏研究报告](research/live-acceptance.md)。该报告只覆盖列出的功能，不代表目录中的所有接口都可用。
