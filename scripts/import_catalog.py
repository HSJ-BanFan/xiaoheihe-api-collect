"""Build a public, allowlisted reference snapshot from explicit local inputs."""
import argparse
import ast
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GROUPS = {
    "账号与设置": "account", "社区内容": "community", "个人资料与社交": "profile",
    "游戏数据": "games", "商城与商店": "mall", "搜索": "search", "消息与通知": "notifications",
    "系统与其他": "system", "任务状态": "tasks", "调试与测试": "debug", "百科": "wiki",
}
FILES = ["client.py", "browse.py", "interaction.py", "groups.py", "login.py", "transport.py", "payload.py", "signer.py", "routes.py", "cli.py"]
SOURCE_IDS = {name: "SRC-" + name.removesuffix(".py").upper() for name in FILES}
NAMED_GROUPS = {
    "/chat_group/my_list": "group list",
    "/chat_group/user/list": "group members",
    "/chatroom/v2/chat_group_msg/list": "group messages",
}
SUPPLEMENTAL_PURPOSES = {
    "/bbs/app/api/link/post": "创建或编辑草稿与帖子，由 draft 和 edit 字段区分",
    "/bbs/app/api/topic/index": "读取创作话题索引，可按帖子关联查询",
    "/bbs/app/comment/create": "创建顶层评论或楼内回复",
    "/bbs/app/comment/delete": "删除评论",
    "/bbs/app/comment/sub/comments": "按楼层评论读取分页回复",
    "/bbs/app/hashtag/link/list": "读取指定标签下的帖子列表",
    "/bbs/app/link/change/status": "改变帖子状态，SDK 用于删除草稿或帖子",
    "/bbs/app/link/edit/info": "读取帖子的当前可编辑内容",
    "/bbs/app/link/favour": "收藏或取消收藏指定帖子",
    "/bbs/app/link/tree": "读取帖子与评论楼层树",
    "/bbs/app/link/tree/v2": "读取精简帖子与评论树",
    "/bbs/app/profile/bbs/comment/list": "读取账号发表的评论列表",
    "/bbs/app/profile/follow/topic": "关注指定话题",
    "/bbs/app/profile/follow/topic/cancel": "取消关注指定话题",
    "/bbs/app/profile/user/link/list": "读取账号的帖子列表",
    "/bbs/app/topic/feeds": "读取指定话题的信息流",
    "/game/dota2/get_player_leaderboards": "读取 Dota 2 玩家排行榜，来自 game_leaderboard 的受限动态展开",
    "/bbs/app/api/qcloud/cos/copy/image/by/url": "把指定外部图片复制到平台图片存储，可带水印选项",
    "/bbs/app/api/qcloud/cos/upload/callback/v2": "报告对象上传完成并读取预览地址",
    "/bbs/app/api/qcloud/cos/upload/heartbeat": "保活上传对象键",
    "/bbs/app/api/qcloud/cos/upload/info/v2": "申请上传对象键、存储桶与区域信息",
    "/bbs/app/api/qcloud/cos/upload/token/v2": "为对象键申请 COS 临时上传凭据",
}


def source_id(name):
    return SOURCE_IDS[name]


def endpoint_id(host, path):
    return hashlib.sha256((host + " " + path).encode()).hexdigest()[:16]


def safe_parameter(item, basis="catalog", location="unknown"):
    if isinstance(item, str):
        return {"name": item, "location": location, "type": "unknown", "name_resolved": None,
                "required": "unverified", "basis": basis}
    return {"name": item["name"], "location": {"field": "form", "query": "query"}.get(item.get("kind"), "unknown"),
            "type": item.get("type", "unknown"), "name_resolved": item.get("resolved"),
            "required": "unverified", "basis": "catalog_static_declaration"}


def historical(entry):
    probe = entry.get("live_probe") or {}
    latest = probe.get("latest") or probe
    result = {"catalog_label": entry.get("evidence_level", "catalog_record"),
              "latest_saved_date": latest.get("checked_date"),
              "latest_saved_outcome": latest.get("outcome"),
              "latest_saved_status": latest.get("status"),
              "has_saved_success": bool(probe.get("historical_success")) or entry.get("evidence_outcome") == "ok",
              "business_effect": "unverified", "current_availability": "unverified", "live_retested_here": False}
    for key in ("latest_saved_outcome", "latest_saved_status"):
        if result[key] not in (None, "ok", "error", "success", "login", "failed", "timeout", "http_error"):
            result[key] = "other"
    if result["latest_saved_date"] and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", result["latest_saved_date"]):
        result["latest_saved_date"] = None
    return result


def make_entry(path, *, host="api.xiaoheihe.cn", collection="supplemental", category="community", purpose=None):
    return {"id": endpoint_id(host, path), "host": host, "path": path, "path_kind": "fixed",
            "collection": collection, "category": category, "purpose": purpose or f"源码引用路径 {path}",
            "purpose_basis": "code_observed", "method_variants": [], "authentication": "unverified",
            "parameters": [], "response": "端点响应结构未核实。没有收录原始响应或真实参数值。",
            "historical": historical({}), "command_history": [], "generic_call_allowed": False, "named_commands": [],
            "sdk_symbols": [], "sources": [], "notes": []}


def dictionary_keys(node, function):
    if isinstance(node, ast.Dict):
        return [k.value for k in node.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)]
    if isinstance(node, ast.Name):
        keys = []
        for candidate in ast.walk(function):
            if isinstance(candidate, ast.AnnAssign) and isinstance(candidate.target, ast.Name) and candidate.target.id == node.id and isinstance(candidate.value, ast.Dict):
                keys.extend(dictionary_keys(candidate.value, function))
            if isinstance(candidate, ast.Assign):
                for target in candidate.targets:
                    if isinstance(target, ast.Name) and target.id == node.id and isinstance(candidate.value, ast.Dict):
                        keys.extend(dictionary_keys(candidate.value, function))
                    elif isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name) and target.value.id == node.id:
                        if isinstance(target.slice, ast.Constant) and isinstance(target.slice.value, str):
                            keys.append(target.slice.value)
        return keys
    return []


def observe_calls(sdk, entries):
    for filename in ("client.py", "browse.py", "interaction.py", "groups.py", "cli.py"):
        tree = ast.parse((sdk / filename).read_text(encoding="utf-8"))
        for function in (x for x in ast.walk(tree) if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef))):
            for call in (x for x in ast.walk(function) if isinstance(x, ast.Call)):
                if not isinstance(call.func, ast.Attribute) or call.func.attr not in ("signed_request", "web_request", "_group_read") or not call.args:
                    continue
                arg = call.args[0]
                paths = []
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and arg.value.startswith("/"):
                    paths = [arg.value]
                elif filename == "browse.py" and function.name == "game_leaderboard" and isinstance(arg, ast.JoinedStr):
                    allowed = next(x.value for x in function.body if isinstance(x, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "allowed" for t in x.targets))
                    paths = [f"/game/{game.value}/get_player_leaderboards" for game in allowed.elts]
                for path in paths:
                    entry = entries.setdefault(path, make_entry(path, category="games" if path.startswith("/game/") else "community"))
                    symbol = filename + ":" + function.name
                    if symbol not in entry["sdk_symbols"]:
                        entry["sdk_symbols"].append(symbol)
                    mode = "web_cookie" if call.func.attr == "web_request" else "app_signed"
                    method = "POST" if mode == "web_cookie" or any(k.arg == "payload" for k in call.keywords) else "GET"
                    variant = {"method": method, "protocol": mode, "basis": "code_observed", "source": source_id(filename)}
                    if variant not in entry["method_variants"]:
                        entry["method_variants"].append(variant)
                    entry["authentication"] = "web_cookie_observed" if mode == "web_cookie" else "app_cookie_and_signature_observed"
                    if source_id(filename) not in entry["sources"]:
                        entry["sources"].append(source_id(filename))
                    params = [(k.arg, k.value) for k in call.keywords if k.arg in ("query", "payload")]
                    if mode == "web_cookie" and len(call.args) > 1:
                        params.append(("payload", call.args[1]))
                    if call.func.attr == "_group_read" and len(call.args) > 2:
                        params.append(("query", call.args[2]))
                        entry["parameters"].append(safe_parameter("chat_group_id", "code_observed", "query"))
                    for kind, node in params:
                        for name in dictionary_keys(node, function):
                            location = "query" if kind == "query" else "form"
                            p = safe_parameter(name, "code_observed", location)
                            if not any(x["name"] == name and x["location"] == location for x in entry["parameters"]):
                                entry["parameters"].append(p)
                    if entry["collection"] == "supplemental":
                        entry["notes"].append("源码调用不等于平台当前可用，HTTP GET 也可能改变状态。")
                    if "/qcloud/" in path:
                        entry["category"] = "upload"


def supplement(entries, sdk):
    specs = [
        ("/account/get_login_code/", "POST", "app_signed_no_session", "请求短信登录验证码", [("phone_num", "form")]),
        ("/account/login_code/", "POST", "app_signed_no_session", "校验短信登录验证码", [("phone_num", "form"), ("code", "query"), ("is_new_device", "query"), ("referrer", "query")]),
        ("/account/wechat/login/v2/web_sso/", "GET", "web_sso", "微信登录入口页面", []),
        ("/account/wechat/login_redirect/v2/web_sso/", "GET", "web_sso", "微信授权回调与会话 Cookie", [("code", "query"), ("state", "query")]),
    ]
    for path, method, protocol, purpose, params in specs:
        item = make_entry(path, category="login", purpose=purpose)
        item["method_variants"] = [{"method": method, "protocol": protocol, "basis": "code_observed", "source": "SRC-LOGIN"}]
        item["parameters"] = [safe_parameter(name, "code_observed", location) for name, location in params]
        item["authentication"] = "no_existing_session_observed"
        item["sources"] = ["SRC-LOGIN"]
        item["named_commands"] = ["account login"]
        item["notes"] = ["登录授权和短信发送会产生外部操作。本轮未运行。会话提取不证明 App 接口身份验证成功。"]
        entries[path] = item
    helper_specs = [
        ("open.weixin.qq.com", "/connect/qrcode/{uuid}", "GET", "web_sso", "微信二维码图像模板", "SRC-LOGIN"),
        ("long.open.weixin.qq.com", "/connect/l/qrconnect", "GET", "web_sso", "微信登录轮询辅助请求", "SRC-LOGIN"),
        ("{bucket}.cos.{region}.myqcloud.com", "/{object_key}", "PUT", "cos_v5", "COS 对象上传模板", "SRC-TRANSPORT"),
    ]
    for host, path, method, protocol, purpose, source in helper_specs:
        item = make_entry(path, host=host, collection="auxiliary", category="upload" if method == "PUT" else "login", purpose=purpose)
        item["path_kind"] = "template" if "{" in host + path else "fixed"
        item["method_variants"] = [{"method": method, "protocol": protocol, "basis": "code_observed", "source": source}]
        item["authentication"] = "temporary_cos_credentials_observed" if method == "PUT" else "no_existing_session_observed"
        item["sources"] = [source]
        if method == "PUT":
            item["notes"] = ["主机和对象路径由上传信息响应决定，也存在加速域名分支。本条是模板，不是固定 API 地址。"]
            item["parameters"] = [safe_parameter("Authorization", "code_observed", "header"), safe_parameter("x-cos-security-token", "code_observed", "header"), safe_parameter("object_bytes", "code_observed", "body")]
        else:
            item["parameters"] = [safe_parameter("uuid", "code_observed", "path" if "{" in path else "query")]
        entries[host + path] = item
    post = entries["/bbs/app/api/link/post"]
    payload_tree = ast.parse((sdk / "payload.py").read_text(encoding="utf-8"))
    build = next(x for x in ast.walk(payload_tree) if isinstance(x, ast.FunctionDef) and x.name == "build")
    for name in dictionary_keys(ast.Name(id="payload"), build):
        if not any(p["name"] == name and p["location"] == "form" for p in post["parameters"]):
            post["parameters"].append(safe_parameter(name, "code_observed", "form"))
    post["sources"].append("SRC-PAYLOAD")
    post["notes"].append("draft、edit 等参数由 Post.build 生成。条件字段和服务端必填性没有在此声称已验证。")


def build(sdk):
    catalog = json.loads((sdk / "api_catalog.json").read_text(encoding="utf-8"))
    entries = {}
    for collection in ("routes", "group_routes", "review_required"):
        for old in catalog[collection]:
            category = "groups" if collection == "group_routes" else GROUPS.get(old.get("group"), "account" if old["route"].startswith("/account/") else "community")
            item = make_entry(old["route"], collection=collection, category=category, purpose=old.get("purpose", "用途待复核"))
            item["purpose_basis"] = old.get("purpose_basis", "catalog_static_or_name_inference")
            item["historical"] = historical(old)
            item["parameters"] = [safe_parameter(p, old.get("params_basis", "catalog")) for p in old.get("params", [])]
            item["generic_call_allowed"] = collection == "routes"
            item["sources"] = ["SRC-CATALOG"]
            item["authentication"] = "default_app_signature_inferred_not_endpoint_verified"
            methods = [(old["method"], "catalog_declared")] if collection != "review_required" else [(old["static_method"], "catalog_static_declared"), (old["snapshot_method"], "catalog_historical_request")]
            item["method_variants"] = [{"method": method, "protocol": "app_default_inferred", "basis": basis, "source": "SRC-CATALOG"} for method, basis in methods]
            if collection == "review_required":
                item["notes"].append(old["reason"])
            if collection == "group_routes":
                item["notes"].append("目录分类为 " + old["classification"] + "。分类、命名和历史接受响应均不证明业务效果。通用 call 始终拒绝。")
                if old["route"] in NAMED_GROUPS:
                    item["named_commands"] = [NAMED_GROUPS[old["route"]]]
            entries[old["route"]] = item
    observe_calls(sdk, entries)
    supplement(entries, sdk)
    for command in catalog["commands"]:
        for path in command["routes"]:
            if path not in entries:
                entries[path] = make_entry(path, purpose="具名命令引用的路径")
                entries[path]["method_variants"] = [{"method": "GET", "protocol": "app_signed", "basis": "code_observed", "source": "SRC-CLI"}]
                entries[path]["authentication"] = "app_cookie_and_signature_observed"
                entries[path]["sources"] = ["SRC-CATALOG", "SRC-CLI"]
            item = entries[path]
            if command["name"] not in item["named_commands"]:
                item["named_commands"].append(command["name"])
            item["command_history"].append({"command": command["name"], "catalog_label": command["evidence_level"],
                                            "scope": "command_or_workflow_not_endpoint", "current_availability": "unverified", "source": "SRC-CATALOG"})
    for item in entries.values():
        if item["path"] in SUPPLEMENTAL_PURPOSES:
            item["purpose"] = SUPPLEMENTAL_PURPOSES[item["path"]]
            item["purpose_basis"] = "code_observed"
        item["notes"] = list(dict.fromkeys(item["notes"]))
        item["sources"] = sorted(set(item["sources"]))
        item["named_commands"].sort()
        item["sdk_symbols"].sort()
        if len({v["method"] for v in item["method_variants"]}) > 1:
            item["notes"].append("同一路径存在 HTTP 方法记录冲突。此页保留各自来源，不能互换或据此确认多个协议均可用。")
    sources = [{"id": "SRC-CATALOG", "artifact": "api_catalog.json", "sha256": hashlib.sha256((sdk / "api_catalog.json").read_bytes()).hexdigest(), "summary": "研究目录的白名单、静态字段及脱敏历史状态摘要。原件不随项目分发。"}]
    for filename in FILES:
        sources.append({"id": source_id(filename), "artifact": filename, "sha256": hashlib.sha256((sdk / filename).read_bytes()).hexdigest(), "summary": "研究 SDK 源码静态观察。未执行网络调用或外部签名器，原件不随项目分发。"})
    return {"schema_version": 1, "snapshot_date": "2026-10-07", "sources": sources,
            "interfaces": sorted(entries.values(), key=lambda x: (x["category"], x["host"], x["path"]))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk-dir", type=Path, required=True, help="Explicit read-only research SDK directory")
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "interfaces.json")
    args = parser.parse_args()
    data = build(args.sdk_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Exported {len(data['interfaces'])} sanitized reference records")


if __name__ == "__main__":
    main()
