import asyncio
import json
import os
from typing import Optional

import httpx
import yaml
from a2a.client import A2AClientHTTPError, A2AClientJSONError
from a2a.types import AgentCard
from httpx import Timeout
from maintainer.ai.nacos_ai_maintainer_service import NacosAIMaintainerService
from pydantic import ValidationError
from v2.nacos import ClientConfigBuilder


async def list_agents_from_nacos(
    nacos_addr: str,
    username: str,
    password: str,
    access_key: str,
    secret_key: str,
    namespace_id: str = "public",
) -> list[str]:
    """List all registered agent names from Nacos."""
    if not nacos_addr:
        return []

    if ':' not in nacos_addr.split('//')[-1]:
        nacos_addr = f"{nacos_addr}:8848"

    nacos_client_config = ClientConfigBuilder().server_address(
        nacos_addr
    ).namespace_id(
        namespace_id
    ).username(username).password(password).access_key(access_key).secret_key(secret_key).build()

    nacos_ai_maintainer_service = await NacosAIMaintainerService.create_ai_service(nacos_client_config)

    from maintainer.common.auth import RequestResource
    from maintainer.transport.client_http_proxy import HttpRequest
    from v2.nacos.common.constants import Constants

    request_resource = RequestResource(
        Constants.AI_MODULE,
        namespace_id,
        "",
        None,
    )
    request = HttpRequest(
        path="/nacos/v3/admin/ai/a2a/list",
        method="GET",
        request_resource=request_resource,
        params={
            "namespaceId": namespace_id,
            "pageNo": 1,
            "pageSize": 200,
            "search": "accurate",
            "agentName": "",
        },
    )
    result = await nacos_ai_maintainer_service.http_proxy.request(request)

    if result.get("code") != 0:
        raise Exception(result.get("message", "Failed to list agents from Nacos"))

    result_data = result["data"]
    page_items = result_data.get("pageItems", [])

    return [item.get("name") for item in page_items if item.get("name")]


TOOL_YAMLS = ["call_a2a_agent.yaml", "get_a2a_agent_information.yaml"]


def sync_agent_options_to_yaml(
    nacos_addr: str,
    username: str = "",
    password: str = "",
    access_key: str = "",
    secret_key: str = "",
    namespace_id: str = "public",
) -> list[str]:
    """
    Query Nacos for registered agents and update tool YAML options in-place.
    """
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    try:
        agent_names = loop.run_until_complete(
            list_agents_from_nacos(nacos_addr, username, password, access_key, secret_key, namespace_id)
        )
    except Exception:
        return []

    if not agent_names:
        return []

    # Build options: *all* first, then each agent
    options = [
        {"value": "*all*", "label": {"en_US": "All Registered Agents", "zh_Hans": "所有已注册智能体"}},
    ]
    for name in sorted(agent_names):
        options.append({"value": name, "label": {"en_US": name, "zh_Hans": name}})

    # Update each tool YAML that has an available_agent_names parameter
    tools_dir = os.path.dirname(__file__)
    for yaml_name in TOOL_YAMLS:
        yaml_path = os.path.join(tools_dir, yaml_name)
        if not os.path.exists(yaml_path):
            continue
        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        params = data.get("parameters", [])
        updated = False
        for param in params:
            if param.get("name") == "available_agent_names":
                param["options"] = options
                updated = True
                break

        if updated:
            with open(yaml_path, "w", encoding="utf-8") as f:
                yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    return agent_names


def parse_available_agents_nacos(available_agent_names: Optional[str]) -> list[str]:
    """
    Parse agent names for Nacos mode.

    Returns empty list for '*all*' sentinel (meaning "all registered agents").
    """
    if not available_agent_names:
        return []
    name = available_agent_names.strip()
    if name == "*all*":
        return []
    return [name] if name else []


def parse_available_agents_url(available_agent_urls: Optional[str]) -> dict[str, str]:
    """Parse JSON mapping of agent names to URLs for URL mode."""
    if not available_agent_urls:
        return {}
    try:
        result = json.loads(available_agent_urls)
        if not isinstance(result, dict):
            raise ValueError("available_agent_urls must be a JSON object")
        return result
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse available_agent_urls as JSON: {e}")


def get_agent_names_list(discovery_type: str, available_agent_names: Optional[str],
                         available_agent_urls: Optional[str]) -> list[str]:
    """Get list of available agent names based on discovery type."""
    if discovery_type == "nacos":
        return parse_available_agents_nacos(available_agent_names)
    elif discovery_type == "url":
        url_mapping = parse_available_agents_url(available_agent_urls)
        return list(url_mapping.keys())
    return []


def validate_target_agent(target_agent: str, discovery_type: str,
                          available_agent_names: Optional[str],
                          available_agent_urls: Optional[str]) -> None:
    """
    Validate that target_agent exists in the available agents list.

    When available_agent_names is empty or '*all*', all agents are allowed.
    """
    available_names = get_agent_names_list(discovery_type, available_agent_names, available_agent_urls)
    if not available_names:
        return  # '*all*' or empty — everything is allowed
    if target_agent not in available_names:
        raise ValueError(f"Target agent '{target_agent}' is not in the available agents list: {available_names}")


async def get_a2a_agent_card(
    agent_type: str,
    a2a_agent_url: str,
    nacos_addr: str,
    a2a_agent_name: str,
    namespace_id: str,
    username: str,
    password: str,
    access_key: str,
    secret_key: str
) -> AgentCard:
    agent_card: AgentCard | None = None
    if agent_type == "url":
        if a2a_agent_url is None:
            raise ValueError("when type is url, a2a_agent_url is required")
        agent_card = await get_agent_card_from_url(a2a_agent_url)
    elif agent_type == "nacos":
        if a2a_agent_name is None:
            raise ValueError("when type is nacos, a2a_agent_name is required")
        if nacos_addr is None:
            raise ValueError("when type is nacos, nacos_addr is required")

        if ':' not in nacos_addr.split('//')[-1]:
            nacos_addr = f"{nacos_addr}:8848"

        nacos_client_config = ClientConfigBuilder().server_address(
            nacos_addr).namespace_id(
            namespace_id).username(
            username).password(
            password).access_key(
            access_key).secret_key(
            secret_key).build()
        nacos_ai_maintainer_service = await NacosAIMaintainerService.create_ai_service(
            nacos_client_config)
        agent_card = await nacos_ai_maintainer_service.get_agent_card(
            namespace_id=namespace_id,
            agent_name=a2a_agent_name,
            registration_type="URL")
    return agent_card


async def get_target_agent_card(
    discovery_type: str,
    target_agent: str,
    available_agent_names: Optional[str],
    available_agent_urls: Optional[str],
    nacos_addr: str,
    namespace_id: str,
    username: str,
    password: str,
    access_key: str,
    secret_key: str
) -> AgentCard:
    """Get AgentCard for the target agent from multi-agent configuration."""
    validate_target_agent(target_agent, discovery_type, available_agent_names, available_agent_urls)

    if discovery_type == "nacos":
        return await get_a2a_agent_card(
            agent_type="nacos",
            a2a_agent_url=None,
            nacos_addr=nacos_addr,
            a2a_agent_name=target_agent,
            namespace_id=namespace_id,
            username=username,
            password=password,
            access_key=access_key,
            secret_key=secret_key
        )
    elif discovery_type == "url":
        url_mapping = parse_available_agents_url(available_agent_urls)
        agent_url = url_mapping.get(target_agent)
        if not agent_url:
            raise ValueError(f"URL not found for agent '{target_agent}'")
        return await get_a2a_agent_card(
            agent_type="url",
            a2a_agent_url=agent_url,
            nacos_addr=None,
            a2a_agent_name=None,
            namespace_id=None,
            username=None,
            password=None,
            access_key=None,
            secret_key=None
        )
    else:
        raise ValueError(f"Invalid discovery_type: {discovery_type}")


async def get_all_agents_info(
    discovery_type: str,
    available_agent_names: Optional[str],
    available_agent_urls: Optional[str],
    nacos_addr: str,
    namespace_id: str,
    username: str,
    password: str,
    access_key: str,
    secret_key: str
) -> list[dict]:
    """Get information for all configured agents.

    When available_agent_names is empty or '*all*', fetches all agents from Nacos at runtime.
    """
    agent_names = get_agent_names_list(discovery_type, available_agent_names, available_agent_urls)

    # Empty / '*all*' in nacos mode: query Nacos directly at runtime
    if not agent_names and discovery_type == "nacos" and nacos_addr:
        agent_names = await list_agents_from_nacos(
            nacos_addr, username, password, access_key, secret_key, namespace_id
        )

    if not agent_names:
        raise ValueError("No available agents configured.")

    results = []
    for agent_name in agent_names:
        try:
            agent_card = await get_target_agent_card(
                discovery_type=discovery_type,
                target_agent=agent_name,
                available_agent_names=available_agent_names,
                available_agent_urls=available_agent_urls,
                nacos_addr=nacos_addr,
                namespace_id=namespace_id,
                username=username,
                password=password,
                access_key=access_key,
                secret_key=secret_key
            )
            results.append({
                "agent_name": agent_name,
                "description": agent_card.description,
                "skills": agent_card.skills,
            })
        except Exception as e:
            results.append({
                "agent_name": agent_name,
                "error": str(e),
            })

    return results


async def get_agent_card_from_url(target_url: str) -> AgentCard:
    _httpx_client = httpx.AsyncClient(timeout=Timeout(10))
    try:
        response = await _httpx_client.get(target_url)
        response.raise_for_status()
        agent_card_data = response.json()
        agent_card = AgentCard.model_validate(agent_card_data)
    except httpx.HTTPStatusError as e:
        raise A2AClientHTTPError(
            e.response.status_code,
            f'Failed to fetch agent card from {target_url}: {e}',
        ) from e
    except json.JSONDecodeError as e:
        raise A2AClientJSONError(
            f'Failed to parse JSON for agent card from {target_url}: {e}'
        ) from e
    except httpx.RequestError as e:
        raise A2AClientHTTPError(
            503,
            f'Network communication error fetching agent card from {target_url}: {e}',
        ) from e
    except ValidationError as e:
        raise A2AClientJSONError(
            f'Failed to validate agent card structure from {target_url}: {e.json()}'
        ) from e

    return agent_card
