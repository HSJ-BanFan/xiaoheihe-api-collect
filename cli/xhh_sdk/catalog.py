"""Offline interface discovery; never loads credentials or runs the signer."""
from __future__ import annotations

import json
from importlib.resources import files


def select(*, search: str = "", route: str | None = None, group: bool = False) -> dict:
    data = json.loads(files("xhh_sdk").joinpath("api_catalog.json").read_text(encoding="utf-8"))
    group_rows = data.get("group_routes", [])
    if route is not None:
        normalized = route.rstrip("/")
        data["routes"] = [r for r in data["routes"] if r["route"] == normalized]
        data["review_required"] = [r for r in data.get("review_required", [])
                                   if r["route"] == normalized]
        data["commands"] = [c for c in data.get("commands", [])
                            if normalized in c.get("routes", [])]
        data["group_routes"] = [r for r in group_rows if r["route"] == normalized]
        if (not data["routes"] and not data["review_required"] and not data["commands"]
                and not data["group_routes"]):
            raise ValueError(f"route not found in catalog: {route}")
    elif search:
        needle = search.casefold()
        for key in ("routes", "commands", "review_required", "group_routes"):
            data[key] = [r for r in data.get(key, [])
                         if needle in json.dumps(r, ensure_ascii=False).casefold()]
    elif group:
        data["routes"] = []
    else:
        data["group_routes"] = []
    return data


def display(data: dict) -> str:
    probe = data.get("summary", {}).get("live_probe", {})
    lines = [
        f"Historical evidence: {data['verification_date']}; "
        f"live re-tested: {'yes' if data.get('live_retested') else 'no'}"
        + (f" ({probe.get('routes_ok')}/{probe.get('routes_probed')} GET ok on "
           f"{probe.get('checked_date')})" if probe.get("live_retested") else ""),
        "GET success is not proof of complete parameters or side-effect freedom.",
        "Use --json or --route PATH for contract details.",
    ]
    for row in data["routes"]:
        lines.append(f"{row['route']}\n  {row['purpose']} [{row['purpose_basis']}]")
        if row.get("params"):
            lines.append("  params: " + json.dumps(row["params"], ensure_ascii=False))
        if row.get("live_probe"):
            lines.append("  live: " + json.dumps(row["live_probe"], ensure_ascii=False))
    for row in data.get("review_required", []):
        lines.append("REVIEW: " + json.dumps(row, ensure_ascii=False))
    if data.get("commands"):
        lines.append("CLI commands:")
        lines.extend(json.dumps(row, ensure_ascii=False) for row in data["commands"])
    if data.get("group_routes"):
        lines.append("App-only group/community routes (not in the generic GET allowlist):")
        for row in data["group_routes"]:
            lines.append(f"{row['route']} [{row['method']}/{row['classification']}] "
                         f"{row['purpose']} gate={row['callable']}")
            if row.get("live_probe"):
                lines.append("  live: " + json.dumps(row["live_probe"], ensure_ascii=False))
    return "\n".join(lines)
