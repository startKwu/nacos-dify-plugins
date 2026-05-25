"""
Sync Nacos agent names into tool YAML as static select options (fallback when Dify
does not call dynamic-options API for tool settings forms).

Usage:
    uv run scripts/sync_agents_to_tool_yaml.py --nacos-addr 127.0.0.1:8848
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.sync_agents import list_nacos_agents

TOOL_YAMLS = (
    "tools/get_a2a_agent_information.yaml",
    "tools/call_a2a_agent.yaml",
)
AGENTS_KEY = "available_agent_names"


def build_options(agent_names: list[str]) -> list[dict]:
    options = [
        {
            "value": "*all*",
            "label": {"en_US": "All Registered Agents", "zh_Hans": "所有已注册智能体"},
        }
    ]
    for name in sorted(agent_names):
        if name:
            options.append({"value": name, "label": {"en_US": name, "zh_Hans": name}})
    return options


def update_tool_yaml(path: str, agent_names: list[str], use_select: bool) -> None:
    root = os.path.join(os.path.dirname(__file__), "..")
    full_path = os.path.join(root, path)
    with open(full_path, encoding="utf-8") as f:
        doc = yaml.safe_load(f)

    for param in doc.get("parameters", []):
        if param.get("name") != AGENTS_KEY:
            continue
        if use_select:
            param["type"] = "select"
            param["options"] = build_options(agent_names)
        else:
            param["type"] = "dynamic-select"
            param.pop("options", None)
        break
    else:
        print(f"  [skip] {path}: no {AGENTS_KEY} parameter")
        return

    with open(full_path, "w", encoding="utf-8") as f:
        yaml.dump(doc, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    print(f"  [ok] {path} -> type={doc['parameters'][1]['type'] if len(doc['parameters'])>1 else 'select'}, {len(agent_names)} agents")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--nacos-addr", default=os.environ.get("NACOS_ADDR", "127.0.0.1:8848"))
    parser.add_argument("--username", default=os.environ.get("NACOS_USERNAME", "nacos"))
    parser.add_argument("--password", default=os.environ.get("NACOS_PASSWORD", "nacos"))
    parser.add_argument("--access-key", default=os.environ.get("NACOS_ACCESS_KEY", ""))
    parser.add_argument("--secret-key", default=os.environ.get("NACOS_SECRET_KEY", ""))
    parser.add_argument("--namespace-id", default="public")
    parser.add_argument(
        "--mode",
        choices=("select", "dynamic-select"),
        default="select",
        help="select = static options in YAML (no dynamic-options API); dynamic-select = restore dynamic type",
    )
    args = parser.parse_args()

    agent_names: list[str] = []
    if args.mode == "select":
        agent_names = await list_nacos_agents(
            nacos_addr=args.nacos_addr,
            username=args.username,
            password=args.password,
            access_key=args.access_key,
            secret_key=args.secret_key,
            namespace_id=args.namespace_id,
        )

    for rel in TOOL_YAMLS:
        update_tool_yaml(rel, agent_names, use_select=args.mode == "select")


if __name__ == "__main__":
    asyncio.run(main())
