# 认证、签名与运行依赖

[返回 API 目录](README.md)

## 证据层级

`code_observed` 表示研究 SDK 使用该请求构造方式。`app_default_inferred` 表示按目录归属推定的默认方式，没有逐接口确认。二者都不是服务端要求的独立证明。

目录中不能据路径数量推导出“所有路径必须签名”。同一路径也可能存在 Web Cookie POST 与目录 GET 等不同观察，需要逐条核对。

## App 请求

研究 `Transport.signed_request` 把 `payload=None` 编为 GET，提供 `payload` 时编为表单 POST。公共查询字段包括 `os_type`、`x_os_type`、`x_client_type`、`os_version`、`version`、`build`、`channel`、`x_app`、`time_zone`、`dw`、`netmode`、`imei`、`device_info` 与 `heybox_id`。

签名器返回字段并入查询字符串，代码排除返回值中的 `path`。已知签名字段名包括 `hkey`、`_time`、`nonce` 与 `_rnd`。本项目不提供签名密钥、签名结果或 JAR。

App Cookie 和网页 Cookie 使用的会话字段不同。附加风控 Cookie 名为 `x_xhh_tokenid`。字段存在不意味着任意端点都接受该 Cookie，也不证明会话当前有效。

## Web 上传与 COS

研究 `web_request` 使用 Cookie 和表单 POST，不调用 App 签名。上传 info、token、callback 和 heartbeat 使用该构造方式。

对象上传另走 COS PUT，使用临时凭据、`Authorization` 与 `x-cos-security-token`。COS 签名不是 App 签名。具体主机和对象路径来自上传信息响应，而不是固定在目录中的接口地址。

## 协议需求不等于客户端初始化需求

原研究客户端在创建 `Transport` 时创建 `Signer`，上传流程也可能先遇到 JAR 或 Java 缺失错误。配套 CLI 的 `0.5.0rc4+standalone.6` 已改为首次签名时才初始化签名器。unsigned Web/COS 请求不再依赖 JAR 初始化；真实上传成功仍需另行验证。

离线目录与帮助不应需要签名器。当前 CLI 的依赖边界及可复跑检查以 [CLI 说明](../cli/README.md)和[发布前检查](../cli/RELEASE.md)为准。

## 响应与失败

研究 transport 对普通 API 响应执行 JSON 对象解码，并接受 `status=ok` 或 `status=success`。身份失败、限流和其他错误分别映射到 SDK 异常。这个通用处理不能替代逐端点响应 schema。

历史响应、HTTP 200 和客户端未抛异常都不能单独证明写操作生效。业务效果需要独立读回或其他经过授权的证据。

以上观察对应 [SRC-TRANSPORT](evidence.md#src-transport)、[SRC-SIGNER](evidence.md#src-signer)和[SRC-CLIENT](evidence.md#src-client)。2026-10-08 的候选版验收覆盖了本地签名自检和部分线上 App 请求，具体结果及未验证范围见[线上验收报告](research/live-acceptance.md)。
