# 证据与验证口径

[返回 API 目录](README.md)

本项目的公开事实源是 `data/interfaces.json`。原始研究样本、账号数据、原始响应和签名器不随项目分发。

## 状态含义

- Observed 表示本轮从源文件直接观察到的结构或调用代码，字段值为 `code_observed`。
- Inferred 表示目录默认协议、路径命名或用途推断，不能升级为线上结论。
- Unverified 表示必填性、业务效果和当前可用性仍缺乏独立验收。
- `latest_saved_*` 是历史记录摘要。日期不是本项目的测试时间，`ok` 不是功能生效证据。
- `catalog_label` 保留原标签，不把旧标签解释为当前验证。

证据 ID 只标识离线输入与摘要，不是假装可公开访问的研究链接。SHA-256 用于重建输入一致性，不证明研究质量。

SRC-CATALOG 的哈希指向迁移研究原件，不是脱敏后 CLI 包内目录。CLI 脱敏快照哈希不同是预期情况，不表示新增了当前线上验证。

## 输入登记

<a id="src-catalog"></a>
### SRC-CATALOG

输入名称为 `api_catalog.json`。

研究目录的白名单、静态字段及脱敏历史状态摘要。原件不随项目分发。

SHA-256 为 `f9425750c5a3442072701ecc63c670b55a981e3f7eecde68a5aa04bc774d37e2`。

<a id="src-client"></a>
### SRC-CLIENT

输入名称为 `client.py`。

研究 SDK 源码静态观察。未执行网络调用或外部签名器，原件不随项目分发。

SHA-256 为 `a6d1a6dac857b35a6ea52adfc1787f983e19d154d3dc6359bd23c3c5e2d6675c`。

<a id="src-browse"></a>
### SRC-BROWSE

输入名称为 `browse.py`。

研究 SDK 源码静态观察。未执行网络调用或外部签名器，原件不随项目分发。

SHA-256 为 `32e9ec642d3fcce1b2f8b98460aa21530f93c75e3361846f78df6d8e5c02fcc5`。

<a id="src-interaction"></a>
### SRC-INTERACTION

输入名称为 `interaction.py`。

研究 SDK 源码静态观察。未执行网络调用或外部签名器，原件不随项目分发。

SHA-256 为 `5afad9aac800b7c3e5cf432e7eee0666542e8b50be55194975db524b5360ab57`。

<a id="src-groups"></a>
### SRC-GROUPS

输入名称为 `groups.py`。

研究 SDK 源码静态观察。未执行网络调用或外部签名器，原件不随项目分发。

SHA-256 为 `7f96d995622909d99bd128f996037fa8ab5ef24ec0e8d4e104c82049765e8f5d`。

<a id="src-login"></a>
### SRC-LOGIN

输入名称为 `login.py`。

研究 SDK 源码静态观察。未执行网络调用或外部签名器，原件不随项目分发。

SHA-256 为 `fac3beea62556d6bfb806828f17d037e4e855d4d54381b4cd22fbace5684b91b`。

<a id="src-transport"></a>
### SRC-TRANSPORT

输入名称为 `transport.py`。

研究 SDK 源码静态观察。未执行网络调用或外部签名器，原件不随项目分发。

SHA-256 为 `b9f75f8bd2c6d4a276f2e7fbe9f1abb626b2a5564e97a2f49df9c54ac2b10c1a`。

<a id="src-payload"></a>
### SRC-PAYLOAD

输入名称为 `payload.py`。

研究 SDK 源码静态观察。未执行网络调用或外部签名器，原件不随项目分发。

SHA-256 为 `688c708c822310ef8107b90ce7fe9a926c9eaef2c9fefa618ed4a348991b36ea`。

<a id="src-signer"></a>
### SRC-SIGNER

输入名称为 `signer.py`。

研究 SDK 源码静态观察。未执行网络调用或外部签名器，原件不随项目分发。

SHA-256 为 `44a44863d9b58fb394881c23901580bd6db40c833bc2bbcd85f7fb7b8a575184`。

<a id="src-routes"></a>
### SRC-ROUTES

输入名称为 `routes.py`。

研究 SDK 源码静态观察。未执行网络调用或外部签名器，原件不随项目分发。

SHA-256 为 `c15211e6b4deecd5e74bdc8dc19547de62de114e42e5d3c636617372826c88a4`。

<a id="src-cli"></a>
### SRC-CLI

输入名称为 `cli.py`。

研究 SDK 源码静态观察。未执行网络调用或外部签名器，原件不随项目分发。

SHA-256 为 `f932227a3896d617d93fee49ef664ee24292921470d8456b323b5cce7efdf639`。
