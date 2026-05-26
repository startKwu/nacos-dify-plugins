"""
A2A Server Endpoint

统一处理 A2A 协议请求：
- GET  /a2a/.well-known/agent.json -> Agent Card
- POST /a2a -> JSON-RPC
"""

import json
from .utils import run_async
import logging
from collections.abc import Mapping

from dify_plugin.config.logger_format import plugin_logger_handler
from werkzeug.wrappers import Request, Response
from dify_plugin import Endpoint

# A2A SDK imports
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCard, AgentSkill, AgentCapabilities

# 本地模块导入
from .adapters import StarletteRequestAdapter, ResponseAdapter
from .conversation import ConversationManager
from .executor import DifyAppAgentExecutor
from .utils import (
    register_agent_card,
    delete_agent_card,
    get_agent_card,
    get_cached_agent_card,
    set_cached_agent_card,
    delete_agent_card_cache,
    needs_registration,
    get_registration_info,
    save_registration_info,
    clear_registration_info,
)

logger = logging.getLogger(__name__)
logger.addHandler(plugin_logger_handler)


class A2aServerEndpoint(Endpoint):
    """
    A2A 协议统一端点

    根据 HTTP 方法分发请求：
    - GET  -> 返回 Agent Card
    - POST -> 处理 JSON-RPC
    """

    def _invoke(self, r: Request, values: Mapping, settings: Mapping) -> Response:
        """请求入口，根据 HTTP 方法分发"""
        method = r.method.upper()
        logger.info(f"A2A Plugin received: {method} {r.path}")

        if method == "GET":
            # 查询参数 ?deregister=true 仅注销，不重新注册
            if r.args.get('deregister', '').lower() == 'true':
                return self._handle_deregister(settings)
            return self._handle_agent_card(settings)
        elif method == "POST":
            return self._handle_jsonrpc(r, settings)
        elif method == "DELETE":
            return self._handle_deregister(settings)
        else:
            return self._json_response(
                {"error": "Method Not Allowed"},
                status=405
            )

    def _handle_deregister(self, settings: Mapping) -> Response:
        """仅从 Nacos 注销，不返回 Agent Card"""
        try:
            agent_card = self._build_agent_card(settings)
            self._deregister_agent(agent_card)
            return self._json_response({"status": "ok", "message": f"Agent '{agent_card.name}' deregistered"})
        except Exception as e:
            logger.exception("Error during deregistration")
            return self._json_response(
                {"error": "Deregistration failed", "message": str(e)},
                status=500
            )

    def _handle_agent_card(self, settings: Mapping) -> Response:
        """处理 GET 请求，返回 Agent Card 并根据配置注册到 Nacos"""
        try:
            agent_card = self._build_agent_card(settings)

            # 根据用户配置决定是否注册到 Nacos
            self._try_register_to_nacos(agent_card, settings)

            return self._json_response(
                agent_card.model_dump(mode='json', exclude_none=True)
            )
        except Exception as e:
            logger.exception("Error building Agent Card")
            return self._json_response(
                {"error": "Internal error", "message": str(e)},
                status=500
            )

    def _deregister_agent(self, agent_card: AgentCard) -> bool:
        """
        使用之前保存的注册信息从 Nacos 注销 Agent。

        Returns:
            True 表示成功注销，False 表示没有找到注册信息或注销失败
        """
        prev_reg = get_registration_info(
            self.session, agent_card.name, agent_card.version
        )
        if not prev_reg:
            print(f"[A2A] No registration info for '{agent_card.name}', nothing to deregister")
            return False

        prev_addr = prev_reg.get('nacos_addr', '')
        prev_ns = prev_reg.get('namespace_id', 'public')
        if not prev_addr:
            clear_registration_info(self.session, agent_card.name, agent_card.version)
            return False

        try:
            print(f"[A2A] Deregistering agent '{agent_card.name}' from Nacos at {prev_addr}")
            run_async(delete_agent_card(
                agent_name=agent_card.name,
                version=agent_card.version,
                nacos_addr=prev_addr,
                namespace_id=prev_ns,
                username=prev_reg.get('username', ''),
                password=prev_reg.get('password', ''),
                access_key=prev_reg.get('access_key', ''),
                secret_key=prev_reg.get('secret_key', ''),
            ))
            delete_agent_card_cache(
                self.session, prev_addr, prev_ns,
                agent_card.name, agent_card.version
            )
            clear_registration_info(self.session, agent_card.name, agent_card.version)

            print(f"[A2A] Deregistered agent '{agent_card.name}' from {prev_addr}")
            return True
        except Exception as e:
            print(f"[A2A] Deregistration skipped: {e}")
            return False

    def _try_register_to_nacos(self, agent_card: AgentCard, settings: Mapping) -> None:
        """
        尝试将 AgentCard 注册到 Nacos

        根据用户配置的 enable_nacos_registry 开关决定是否注册。
        使用缓存避免频繁查询和注册，只有当 AgentCard 变更时才注册。
        当配置变更或禁用时，自动从 Nacos 注销旧记录。
        注册失败不影响 Agent Card 的正常返回。
        """
        # 获取 Nacos 配置参数
        enable_nacos = settings.get('enable_nacos_registry', True)
        nacos_addr = settings.get('nacos_addr', '')
        namespace_id = (settings.get('nacos_namespace_id', 'public') or 'public')
        username = settings.get('nacos_username', '') or ''
        password = settings.get('nacos_password', '') or ''
        access_key = settings.get('nacos_accessKey', '') or ''
        secret_key = settings.get('nacos_secretKey', '') or ''

        # ========== 检查是否需要注销（配置删除/禁用时） ==========
        reg_disabled = not enable_nacos or not nacos_addr

        if reg_disabled:
            self._deregister_agent(agent_card)
            return

        # ========== 执行注册 ==========
        try:
            # 1. 从缓存获取已注册的 AgentCard（缓存过期会自动从 Nacos 获取）
            cached_card = get_cached_agent_card(
                session=self.session,
                nacos_addr=nacos_addr,
                namespace_id=namespace_id,
                agent_name=agent_card.name,
                version=agent_card.version,
                username=username,
                password=password,
                access_key=access_key,
                secret_key=secret_key
            )

            # 2. 判断是否需要注册
            if not needs_registration(agent_card, cached_card):
                print(f"[A2A] Agent '{agent_card.name}' already registered, skipping")
                return

            # 3. Agent 已存在 Nacos，先注销旧记录（Nacos 不支持同名 agent 直接覆盖）
            if cached_card:
                try:
                    print(f"[A2A] Agent already exists, deregistering old card first")
                    run_async(delete_agent_card(
                        agent_name=agent_card.name,
                        version=agent_card.version,
                        nacos_addr=nacos_addr,
                        namespace_id=namespace_id,
                        username=username,
                        password=password,
                        access_key=access_key,
                        secret_key=secret_key,
                    ))
                    delete_agent_card_cache(
                        self.session, nacos_addr, namespace_id,
                        agent_card.name, agent_card.version
                    )
                    print(f"[A2A] Old card deregistered (was: {cached_card.url})")
                except Exception as e:
                    # Nacos 可能没有旧记录（首次部署等情况），忽略错误
                    print(f"[A2A] Old card deregistration skipped: {e}")

            # 4. 执行注册
            run_async(register_agent_card(
                agent_card=agent_card,
                nacos_addr=nacos_addr,
                namespace_id=namespace_id,
                username=username,
                password=password,
                access_key=access_key,
                secret_key=secret_key,
            ))

            # 5. 注册成功后从 Nacos 查询并更新缓存
            remote_card = run_async(get_agent_card(
                agent_name=agent_card.name,
                version=agent_card.version,
                nacos_addr=nacos_addr,
                namespace_id=namespace_id,
                username=username,
                password=password,
                access_key=access_key,
                secret_key=secret_key,
            ))

            if remote_card:
                set_cached_agent_card(
                    session=self.session,
                    nacos_addr=nacos_addr,
                    namespace_id=namespace_id,
                    agent_card=remote_card
                )

            # 6. 保存注册信息（用于后续配置变更时取消注册）
            save_registration_info(
                self.session, agent_card.name, agent_card.version,
                nacos_addr, namespace_id,
                username, password, access_key, secret_key
            )

            print(f"[A2A] Successfully registered agent '{agent_card.name}' to Nacos at {nacos_addr}")
            logger.info(f"Agent '{agent_card.name}' registered to Nacos at {nacos_addr}")

        except Exception as e:
            # 注册失败不影响正常流程，仅记录日志
            print(f"[A2A] Nacos registration failed (non-blocking): {e}")
            logger.warning(f"Failed to register agent card to Nacos: {e}")

    def _handle_jsonrpc(self, r: Request, settings: Mapping) -> Response:
        """处理 POST 请求，JSON-RPC 调用"""
        try:
            # 1. 解析 JSON-RPC 请求
            request_data = r.get_json(force=True)
            logger.debug(f"JSON-RPC request: {request_data}")

            # 2. 创建 Starlette 请求适配器
            starlette_request = StarletteRequestAdapter(r)

            # 3. 获取 App 配置
            app_config = settings.get('app', {})
            app_id = app_config.get('app_id', '')

            # 4. 创建会话管理器
            conversation_manager = ConversationManager(
                session=self.session,
                app_id=app_id,
            )

            # 5. 创建执行器
            agent_executor = DifyAppAgentExecutor(
                session=self.session,
                app_config=app_config,
                conversation_manager=conversation_manager,
                nacos_config={
                    'nacos_addr': settings.get('nacos_addr', ''),
                    'namespace_id': settings.get('nacos_namespace_id', 'public') or 'public',
                    'username': settings.get('nacos_username', '') or '',
                    'password': settings.get('nacos_password', '') or '',
                    'access_key': settings.get('nacos_accessKey', '') or '',
                    'secret_key': settings.get('nacos_secretKey', '') or '',
                    'agent_name': settings.get('agent_name', 'Dify A2A Agent'),
                    'version': settings.get('agent_version', '1.0.0'),
                },
            )

            # 6. 创建请求处理器
            request_handler = DefaultRequestHandler(
                agent_executor=agent_executor,
                task_store=InMemoryTaskStore(),
            )

            # 7. 创建 A2A 应用
            agent_card = self._build_agent_card(settings)
            app = A2AStarletteApplication(
                agent_card=agent_card,
                http_handler=request_handler,
            )

            # 8. 调用处理方法（异步转同步）
            starlette_response = run_async(
                app._handle_requests(starlette_request)
            )

            # 9. 转换响应
            return ResponseAdapter.to_werkzeug(starlette_response)

        except json.JSONDecodeError as e:
            return self._json_error_response(
                code=-32700,
                message="Parse error",
                data=str(e)
            )
        except Exception as e:
            logger.exception("Error handling JSON-RPC request")
            return self._json_error_response(
                code=-32603,
                message="Internal error",
                data=str(e)
            )

    def _build_agent_card(self, settings: Mapping) -> AgentCard:
        """根据用户配置构建 AgentCard"""
        # 创建默认技能
        skill = AgentSkill(
            id='dify_app',
            name=settings.get('agent_name', 'Dify App'),
            description=settings.get('agent_description', 'A Dify-powered agent'),
            tags=['dify', 'chatbot'],
            examples=['Hello', 'Help me with...'],
        )

        # 创建能力声明（所有字段可选）
        capabilities = AgentCapabilities(
            streaming=False,  # 不支持流式响应
            state_transition_history=False,
            push_notifications=False,
        )

        return AgentCard(
            name=settings.get('agent_name', 'Dify A2A Agent'),
            description=settings.get('agent_description', 'A2A Agent powered by Dify'),
            url=settings.get('agent_url', 'http://localhost/'),
            version=settings.get('agent_version', '1.0.0'),
            capabilities=capabilities,
            default_input_modes=['text'],
            default_output_modes=['text'],
            skills=[skill],
        )

    def _json_response(self, data: dict, status: int = 200) -> Response:
        """创建 JSON 响应"""
        return Response(
            json.dumps(data, ensure_ascii=False),
            status=status,
            content_type='application/json'
        )

    def _json_error_response(
        self,
        code: int,
        message: str,
        data: str = None,
        request_id=None,
        status: int = 200
    ) -> Response:
        """创建 JSON-RPC 错误响应"""
        error_response = {
            "jsonrpc": "2.0",
            "error": {
                "code": code,
                "message": message,
            },
            "id": request_id
        }
        if data:
            error_response["error"]["data"] = data
        return self._json_response(error_response, status=status)
