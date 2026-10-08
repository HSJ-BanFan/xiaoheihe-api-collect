"""Generate API reference pages from the public snapshot without network access."""
import argparse
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATEGORIES = {"account": "账号与设置", "community": "社区与创作", "profile": "个人资料与社交", "games": "游戏数据",
              "mall": "商城与商店", "search": "搜索", "notifications": "消息与通知", "system": "系统与其他",
              "tasks": "任务状态", "debug": "调试与测试", "wiki": "百科", "groups": "群聊与语音社群",
              "login": "登录与会话", "upload": "图片与对象上传"}
ENTRY_KEYS = {"id", "host", "path", "path_kind", "collection", "category", "purpose", "purpose_basis", "method_variants",
              "authentication", "parameters", "response", "historical", "command_history", "generic_call_allowed", "named_commands", "sdk_symbols", "sources", "notes"}
PARAM_KEYS = {"name", "location", "type", "name_resolved", "required", "basis"}
HISTORY_KEYS = {"catalog_label", "latest_saved_date", "latest_saved_outcome", "latest_saved_status", "has_saved_success", "business_effect", "current_availability", "live_retested_here"}


def exact_keys(value, allowed):
    if set(value) != allowed:
        raise ValueError(f"unexpected or missing fields: {sorted(set(value) ^ allowed)}")


def validate_data(data):
    exact_keys(data, {"schema_version", "snapshot_date", "sources", "interfaces"})
    if data["schema_version"] != 1:
        raise ValueError("unsupported schema")
    sources = set()
    for source in data["sources"]:
        exact_keys(source, {"id", "artifact", "sha256", "summary"})
        if not re.fullmatch(r"[a-f0-9]{64}", source["sha256"]):
            raise ValueError("invalid evidence hash")
        sources.add(source["id"])
    ids, paths = set(), set()
    for entry in data["interfaces"]:
        exact_keys(entry, ENTRY_KEYS)
        exact_keys(entry["historical"], HISTORY_KEYS)
        if entry["id"] in ids or (entry["host"], entry["path"]) in paths:
            raise ValueError("duplicate endpoint identity")
        ids.add(entry["id"])
        paths.add((entry["host"], entry["path"]))
        if not re.fullmatch(r"[a-f0-9]{16}", entry["id"]) or not entry["path"].startswith("/"):
            raise ValueError("invalid endpoint identity")
        if entry["category"] not in CATEGORIES or not set(entry["sources"]) <= sources:
            raise ValueError("invalid category or evidence reference")
        if entry["generic_call_allowed"] != (entry["collection"] == "routes"):
            raise ValueError("generic allowlist drift")
        if entry["historical"]["live_retested_here"] is not False or entry["historical"]["current_availability"] != "unverified":
            raise ValueError("snapshot cannot claim live verification")
        for parameter in entry["parameters"]:
            exact_keys(parameter, PARAM_KEYS)
            if parameter["required"] != "unverified":
                raise ValueError("parameter requirement needs reviewed evidence")
        for history in entry["command_history"]:
            exact_keys(history, {"command", "catalog_label", "scope", "current_availability", "source"})
            if history["scope"] != "command_or_workflow_not_endpoint" or history["current_availability"] != "unverified" or history["source"] not in sources:
                raise ValueError("invalid command history scope")
        for variant in entry["method_variants"]:
            exact_keys(variant, {"method", "protocol", "basis", "source"})
            if variant["method"] not in ("GET", "POST", "PUT") or variant["source"] not in sources:
                raise ValueError("invalid method variant")
    collections = Counter(x["collection"] for x in data["interfaces"])
    for name, expected in (("routes", 243), ("group_routes", 167), ("review_required", 9)):
        if collections[name] != expected:
            raise ValueError(f"catalog count drift: {name} != {expected}")


def load_data(root):
    data = json.loads((root / "data" / "interfaces.json").read_text(encoding="utf-8"))
    validate_data(data)
    return data


def cell(value):
    return str(value).replace("|", "\\|").replace("\n", " ")


def page_path(entry):
    return f"docs/{entry['category']}/{entry['id']}.md"


def render_endpoint(entry):
    history = entry["historical"]
    lines = [f"# {entry['path']}", "", f"[返回{CATEGORIES[entry['category']]}](README.md) · [全目录](../README.md)", "",
             "## 用途", "", entry["purpose"], "", f"用途依据为 `{entry['purpose_basis']}`。路径或名称推断不代表逐项功能验收。", "",
             "## 请求与认证", "", f"主机为 `{entry['host']}`。路径类型为 `{entry['path_kind']}`。端点 ID 为 `{entry['id']}`。", "",
             "| HTTP 方法 | 协议记录 | 依据 | 证据 |", "|---|---|---|---|"]
    for variant in entry["method_variants"]:
        lines.append(f"| {variant['method']} | `{variant['protocol']}` | `{variant['basis']}` | [{variant['source']}](../evidence.md#{variant['source'].lower()}) |")
    lines += ["", f"认证记录为 `{entry['authentication']}`。参见[公共认证与签名说明](../authentication.md)。",
              "", "`app_default_inferred` 只是目录默认推断。`code_observed` 只证明研究 SDK 构造了该请求，不能证明服务端强制要求该签名。",
              "", "## 参数", "", "下表只列已收集的名称与位置，不包含真实值。必填性、可选范围和服务端约束未逐项核实。空表不代表接口没有参数。", "",
              "| 名称 | 位置 | 类型 | 名称已解析 | 必填性 | 依据 |", "|---|---|---|---|---|---|"]
    for parameter in entry["parameters"]:
        lines.append("| " + " | ".join(cell(parameter[key]) for key in ("name", "location", "type", "name_resolved", "required", "basis")) + " |")
    if not entry["parameters"]:
        lines.append("| 未收集 | 未核实 | 未核实 | 未核实 | 未核实 | 不推定无参数 |")
    lines += ["", "未解析的常量表达式保留原名，不应直接作为 HTTP 参数名。`unknown` 位置不得自动当作查询参数。公共设备与签名字段见[认证说明](../authentication.md)。",
              "", "## 响应", "", entry["response"], "",
              "研究 transport 通常解码 JSON 对象并检查 `status`。这不是本接口的响应 schema。网页、二维码和 COS 请求也不适用统一 JSON 假设。",
              "", "## 验证状态", "", "| 项目 | 记录 |", "|---|---|"]
    labels = [("目录原标签", "catalog_label"), ("最新保存日期", "latest_saved_date"), ("最新保存结果", "latest_saved_outcome"),
              ("最新保存 status", "latest_saved_status"), ("保存过成功记录", "has_saved_success"), ("业务效果", "business_effect"),
              ("当前可用性", "current_availability"), ("本项目重新线上测试", "live_retested_here")]
    lines += [f"| {label} | `{history[key]}` |" for label, key in labels]
    lines += ["", "历史 `ok` 仅表示保存的响应状态。历史接受不等于业务生效，也不等于当前可用。本轮没有发出线上请求。"]
    if entry["command_history"]:
        lines += ["", "### 命令级历史证据", "", "以下标签来自历史命令或复合工作流，不能作为此端点的独立验收，也不是本轮线上验证。", "", "| 命令 | 历史标签 | 证据 |", "|---|---|---|"]
        for item in entry["command_history"]:
            lines.append(f"| `{item['command']}` | `{item['catalog_label']}` | [{item['source']}](../evidence.md#{item['source'].lower()}) |")
    lines += ["", "## CLI 与 SDK 入口", ""]
    if entry["generic_call_allowed"]:
        lines += ["该路径在通用 GET 白名单内。白名单是客户端门禁，不是平台安全承诺。参数需先按证据核实，命令格式见 [CLI 附录](../cli.md)。"]
    else:
        lines += ["该路径不在通用 `call` 白名单内。不要使用通用调用绕过门禁。目录收录不代表存在可调用的 HTTP 接口。"]
    if entry["named_commands"]:
        lines += ["", "目录关联的具名命令为 " + "、".join(f"`{x}`" for x in entry["named_commands"]) + "。这是入口映射，不是运行建议或本轮验收结果。"]
    else:
        lines += ["", "没有收录具名 CLI 入口。"]
    if entry["sdk_symbols"]:
        lines += ["", "研究 SDK 符号为 " + "、".join(f"`{x}`" for x in entry["sdk_symbols"]) + "。SDK 方法存在不改变通用门禁。"]
    lines += ["", "## 证据与限制", ""]
    lines += [f"- [{source}](../evidence.md#{source.lower()})。" for source in entry["sources"]]
    lines += ["- " + note for note in entry["notes"]]
    lines += ["", "本页由公开脱敏数据生成。修改来源与状态需遵守[贡献指南](../../CONTRIBUTING.md)。", ""]
    return "\n".join(lines)


def render(data):
    pages = {}
    counts = Counter(x["category"] for x in data["interfaces"])
    collections = Counter(x["collection"] for x in data["interfaces"])
    fixed_api = sum(x["host"] == "api.xiaoheihe.cn" and x["path_kind"] == "fixed" for x in data["interfaces"])
    lines = ["# 小黑盒 API 参考目录", "", "[项目首页](../README.md) · [认证与签名](authentication.md) · [登录说明](login.md) · [证据口径](evidence.md) · [研究报告](research/README.md) · [CLI 附录](cli.md)", "",
             f"当前快照包含 {len(data['interfaces'])} 条参考记录，其中 {fixed_api} 条为 `api.xiaoheihe.cn` 固定路径，另有辅助固定路径或模板。",
             "这不是小黑盒所有实际 HTTP 接口的全集。动态构造、未纳入源码和未完成的静态研究仍可能留下缺项。", "",
             f"原目录保留 {collections['routes']} 条通用 GET、{collections['group_routes']} 条群路由及 {collections['review_required']} 条待复核记录。",
             f"另补 {collections['supplemental']} 条源码或登录路径与 {collections['auxiliary']} 条辅助请求记录。路径末尾斜杠保持源码写法，不推定服务器等价。", "",
             "## 按业务浏览", "", "| 业务 | 参考记录数 |", "|---|---:|"]
    for category, title in CATEGORIES.items():
        if counts[category]:
            lines.append(f"| [{title}]({category}/README.md) | {counts[category]} |")
            entries = [x for x in data["interfaces"] if x["category"] == category]
            category_lines = [f"# {title}", "", "[返回全目录](../README.md)", "", f"本业务共 {len(entries)} 条参考记录。每个条目分别保留方法、参数、响应缺口、认证依据及验证状态。", "",
                              "目录项、静态字符串、SDK 调用与 HTTP 实存接口不是同一概念。分类仅便于导航。", "", "| 路径 | 方法记录 | 收录分区 |", "|---|---|---|"]
            for entry in entries:
                methods = ", ".join(sorted({v["method"] for v in entry["method_variants"]}))
                category_lines.append(f"| [{cell(entry['path'])}]({entry['id']}.md) | {methods} | `{entry['collection']}` |")
                pages[page_path(entry)] = render_endpoint(entry)
            pages[f"docs/{category}/README.md"] = "\n".join(category_lines) + "\n"
    pages["docs/README.md"] = "\n".join(lines) + "\n"
    evidence = ["# 证据与验证口径", "", "[返回 API 目录](README.md)", "",
                "本项目的公开事实源是 `data/interfaces.json`。原始研究样本、账号数据、原始响应和签名器不随项目分发。", "",
                "## 状态含义", "", "- Observed 表示本轮从源文件直接观察到的结构或调用代码，字段值为 `code_observed`。",
                "- Inferred 表示目录默认协议、路径命名或用途推断，不能升级为线上结论。",
                "- Unverified 表示必填性、业务效果和当前可用性仍缺乏独立验收。",
                "- `latest_saved_*` 是历史记录摘要。日期不是本项目的测试时间，`ok` 不是功能生效证据。",
                "- `catalog_label` 保留原标签，不把旧标签解释为当前验证。", "",
                "证据 ID 只标识离线输入与摘要，不是假装可公开访问的研究链接。SHA-256 用于重建输入一致性，不证明研究质量。", "",
                "SRC-CATALOG 的哈希指向迁移研究原件，不是脱敏后 CLI 包内目录。CLI 脱敏快照哈希不同是预期情况，不表示新增了当前线上验证。", "",
                "## 输入登记", ""]
    for source in data["sources"]:
        evidence += [f"<a id=\"{source['id'].lower()}\"></a>", f"### {source['id']}", "", f"输入名称为 `{source['artifact']}`。", "", source["summary"], "", f"SHA-256 为 `{source['sha256']}`。", ""]
    pages["docs/evidence.md"] = "\n".join(evidence)
    return pages


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    pages = render(load_data(args.root))
    failures = []
    for relative, content in pages.items():
        target = args.root / relative
        if args.check:
            if not target.is_file() or target.read_text(encoding="utf-8") != content:
                failures.append(relative)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8", newline="\n")
    if failures:
        print("Generated reference drift: " + ", ".join(failures))
        return 1
    print(f"{'Checked' if args.check else 'Generated'} {len(pages)} reference files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
