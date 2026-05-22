import asyncio
import logging

from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.config.logger_format import plugin_logger_handler
from dify_plugin.entities.tool import ToolInvokeMessage, ParameterOption


from tools.utils import get_all_agents_info, get_agent_names_list, list_agents_from_nacos

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.addHandler(plugin_logger_handler)


class GetA2aAgentInformationTool(Tool):

	def _fetch_parameter_options(self, parameter: str, credentials: dict[str, Any]) -> list[ParameterOption]:
		if parameter != "available_agent_names":
			return []

		# Always include *all* option as fallback
		options = [
			ParameterOption(value="*all*", label={"en_US": "All Registered Agents", "zh_Hans": "所有已注册智能体"})
		]

		nacos_addr = credentials.get("nacos_addr")
		if not nacos_addr:
			return options

		try:
			loop = asyncio.get_event_loop()
		except RuntimeError:
			loop = asyncio.new_event_loop()
			asyncio.set_event_loop(loop)

		try:
			agent_names = loop.run_until_complete(list_agents_from_nacos(
				nacos_addr=nacos_addr,
				username=credentials.get("nacos_username") or "",
				password=credentials.get("nacos_password") or "",
				access_key=credentials.get("nacos_accessKey") or "",
				secret_key=credentials.get("nacos_secretKey") or "",
			))
			for name in agent_names:
				options.append(ParameterOption(value=name, label={"en_US": name, "zh_Hans": name}))
		except Exception as e:
			logger.error(f"Failed to fetch agent options from Nacos: {e}")

		return options

	def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[
		ToolInvokeMessage]:

		# Get discovery configuration
		discovery_type = tool_parameters.get("discovery_type")
		available_agent_names = tool_parameters.get("available_agent_names")
		available_agent_urls = tool_parameters.get("available_agent_urls")
		namespace_id = tool_parameters.get("namespace_id")

		# Get Nacos credentials
		nacos_addr = self.runtime.credentials.get("nacos_addr")
		username = self.runtime.credentials.get("nacos_username")
		password = self.runtime.credentials.get("nacos_password")
		access_key = self.runtime.credentials.get("nacos_accessKey")
		secret_key = self.runtime.credentials.get("nacos_secretKey")

		# Log available agents for debugging
		available_names = get_agent_names_list(discovery_type, available_agent_names, available_agent_urls)
		logger.info(f"Getting information for all available agents: {available_names}")

		try:
			loop = asyncio.get_event_loop()
		except RuntimeError:
			loop = asyncio.new_event_loop()
			asyncio.set_event_loop(loop)

		try:
			agents_info = loop.run_until_complete(get_all_agents_info(
					discovery_type=discovery_type,
					available_agent_names=available_agent_names,
					available_agent_urls=available_agent_urls,
					nacos_addr=nacos_addr,
					namespace_id=namespace_id,
					username=username,
					password=password,
					access_key=access_key,
					secret_key=secret_key,
			))
		except Exception as e:
			logger.error(f"Error getting agents information: {e}")
			raise

		yield self.create_json_message({
			"agents": agents_info
		})
