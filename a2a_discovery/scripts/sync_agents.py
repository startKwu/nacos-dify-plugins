"""
Sync agent names from Nacos to the provider YAML.

This updates the `available_agent_names` options in provider/a2a_discovery.yaml
so the Dify UI shows a dropdown with all registered agents.

Usage:
    uv run scripts/sync_agents.py --nacos-addr 127.0.0.1:8848 --username nacos --password nacos
    uv run scripts/sync_agents.py  # uses env: NACOS_ADDR, NACOS_USERNAME, NACOS_PASSWORD
"""

import argparse
import os
import re
import sys

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from maintainer.ai.nacos_ai_maintainer_service import NacosAIMaintainerService
from v2.nacos import ClientConfigBuilder


async def list_nacos_agents(nacos_addr, username, password, access_key, secret_key, namespace_id="public"):
    if ":" not in nacos_addr.split("//")[-1]:
        nacos_addr = f"{nacos_addr}:8848"

    config = (
        ClientConfigBuilder()
        .server_address(nacos_addr)
        .namespace_id(namespace_id)
        .username(username)
        .password(password)
        .access_key(access_key)
        .secret_key(secret_key)
        .build()
    )
    service = await NacosAIMaintainerService.create_ai_service(config)

    from maintainer.common.auth import RequestResource
    from maintainer.transport.client_http_proxy import HttpRequest
    from v2.nacos.common.constants import Constants

    request_resource = RequestResource(Constants.AI_MODULE, namespace_id, "", None)
    request = HttpRequest(
        path="/nacos/v3/admin/ai/a2a/list",
        method="GET",
        request_resource=request_resource,
        params={"namespaceId": namespace_id, "pageNo": 1, "pageSize": 200, "search": "accurate", "agentName": ""},
    )
    result = await service.http_proxy.request(request)

    if result.get("code") != 0:
        raise Exception(result.get("message", "Failed to list agents from Nacos"))

    page_items = result["data"].get("pageItems", [])
    return [item.get("name") for item in page_items if item.get("name")]


def update_yaml_options(yaml_path, agent_names):
    with open(yaml_path, "r", encoding="utf-8") as f:
        content = f.read()

    provider = yaml.safe_load(content)
    agents_key = "available_agent_names"

    if agents_key not in provider.get("credentials_for_provider", {}):
        print(f"Error: '{agents_key}' not found in {yaml_path}")
        return False

    # Build new options: *all* first, then each agent
    options = [
        {"value": "*all*", "label": {"en_US": "All Registered Agents", "zh_Hans": "所有已注册智能体"}}
    ]
    for name in sorted(agent_names):
        if name:
            options.append({"value": name, "label": {"en_US": name, "zh_Hans": name}})

    provider["credentials_for_provider"][agents_key]["options"] = options

    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.dump(provider, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    print(f"Updated {yaml_path} with {len(agent_names)} agents: {', '.join(agent_names)}")
    return True


def main():
    parser = argparse.ArgumentParser(description="Sync Nacos agents to provider YAML")
    parser.add_argument("--nacos-addr", default=os.environ.get("NACOS_ADDR", "127.0.0.1:8848"))
    parser.add_argument("--username", default=os.environ.get("NACOS_USERNAME", "nacos"))
    parser.add_argument("--password", default=os.environ.get("NACOS_PASSWORD", "nacos"))
    parser.add_argument("--access-key", default=os.environ.get("NACOS_ACCESS_KEY", ""))
    parser.add_argument("--secret-key", default=os.environ.get("NACOS_SECRET_KEY", ""))
    parser.add_argument("--namespace-id", default="public")
    parser.add_argument(
        "--yaml-path",
        default=os.path.join(os.path.dirname(__file__), "..", "provider", "a2a_discovery.yaml"),
    )
    args = parser.parse_args()

    import asyncio

    agent_names = asyncio.run(
        list_nacos_agents(
            nacos_addr=args.nacos_addr,
            username=args.username,
            password=args.password,
            access_key=args.access_key,
            secret_key=args.secret_key,
            namespace_id=args.namespace_id,
        )
    )

    if not agent_names:
        print("No agents found in Nacos.")
        return

    update_yaml_options(args.yaml_path, agent_names)


if __name__ == "__main__":
    main()
