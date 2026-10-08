# 贡献指南

## 修改一个接口条目

1. 在 `data/interfaces.json` 中找到稳定端点 ID。
2. 只修改有证据支持的字段。
3. 为新增观察登记证据 ID、输入名称、摘要和 SHA-256。
4. 运行 `python scripts/generate_reference.py`。
5. 运行 `python scripts/check_repo.py` 和 `python -m unittest discover -s tests -v`。

不要直接编辑带有自动生成说明的接口页。业务分类目录也由同一份数据生成。

## 记录证据

- 把代码观察、历史响应、用途推断和当前实测分开。
- 有 `status=ok` 时，不把业务效果或当前可用性改为已验证。
- 有方法冲突时，保留两个来源，不删除不方便的那条记录。
- 不知道参数是否必填时保留 `unverified`。静态常量尚未解析时保留 `name_resolved=false`。
- 端点响应缺少证据时写明缺口，不制造响应示例或字段类型。
- 添加 CLI 入口需同时核对客户端门禁，不向非白名单条目推荐通用调用。

## 保护隐私与来源

禁止提交账号库、配置实值、Cookie、手机号、验证码、Token、原始响应、设备实值、绝对宿主路径、APK、DEX、JAR 或可执行文件。

证据 ID 是研究输入的公开摘要，不是虚构 URL。私有原件不在公共仓库中，需要原件的验证必须明确说明不可公开复跑。

## 重建研究导入

只有持有授权原件的人需要这一步。普通维护只使用公开 JSON。

```console
python scripts/import_catalog.py --sdk-dir <authorized-research-sdk-directory>
python scripts/generate_reference.py
python scripts/check_repo.py
```

导入器只读取显式指定目录内的 API 目录与源码文件，不导入账号库，不执行源文件，不请求网络。它通过字段白名单创建新数据，不直接复制原 JSON。

## 发布边界

完成本地检查不等于允许发布。发布前需完成权属审核、完整文件清单复核、脱敏人工复核和 CLI 发布前检查。未经明确授权不推送仓库、不发布包、不部署网站。
