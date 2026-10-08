# 登录与会话流程

[返回 API 目录](README.md) · [登录接口条目](login/README.md) · [登录与签名研究](research/authentication-and-signing.md)

## 微信扫码

CLI 提供两种扫码实现。account login --method qr 通过 HTTP 轮询微信授权并请求小黑盒回调。account login --method browser 使用一次性 Playwright 浏览器上下文。两者都走 Web SSO。

2026-10-08 的线上测试中，两种流程都读到了会话 cookie，但用这些会话发出的 App 与 Web 请求都返回 status=relogin。它们目前不能作为本项目可用的接口会话。

登录命令会把返回的会话先写入所选账号，再立即尝试 App 签名身份核对。若核对失败，命令返回非零并报告 expired、rejected 或 identity_unverified。失败的本地会话仍会留在账号库中。使用 account logout <alias> 清除；使用 account status <alias> --online 检查当前 App 会话。不要把本地 authenticated 状态当作服务器接受凭据的证明。

## 短信验证码

account login --method sms 使用 App 签名流程。发送阶段调用 /account/get_login_code/，校验阶段调用 /account/login_code/。发送请求使用加密后的手机号字段，校验请求还带有 code、is_new_device 与 referrer。

2026-10-08 的授权验收完成了风险 token 获取、短信发送、验证码提交、会话保存和 App 身份读回。该流程是当前唯一通过线上验收的 App 登录方式。实际使用需要配置签名器和身份，并通过 --confirm 确认短信发送或登录操作。

风控 cookie x_xhh_tokenid 可由网站页面生成，不要求先登录。它不是 App 会话，也不代表请求已获授权。使用风险 token 时，不要把真实值放入命令历史、问题报告或项目文件。

## 本地账号数据

Windows 上的账号库使用 DPAPI 保护会话字段。每个别名可单独配置设备参数和 signer bundle。CLI 的离线账号列表不会检查服务器是否仍接受会话。

文档不保存手机号、验证码、cookie、账号 ID 或真实别名。接口字段和源码证据见 [登录接口条目](login/README.md)与[SRC-LOGIN](evidence.md#src-login)。
