# A2A Discovery 项目总结

## 项目概述

**项目名称**: A2A Agent Client (a2a_discovery)  
**版本**: 0.0.1  
**作者**: nacos  
**运行环境**: Python 3.12  
**框架**: Dify Plugin

这是一个 Dify 插件项目，用于发现和调用 A2A (Agent-to-Agent) 智能体。支持两种发现方式：
1. **Nacos 智能体注册中心** - 通过 Nacos 服务发现 A2A Agent
2. **直接 URL 访问** - 通过预配置的 URL 直接访问 A2A Agent

---

## 项目结构

```
a2a_discovery/
├── manifest.yaml              # 插件清单配置
├── main.py                    # 插件入口文件
├── requirements.txt           # Python 依赖
├── provider/                  # Provider 模块
│   ├── a2a_discovery.py       # Provider 实现
│   └── a2a_discovery.yaml     # Provider 配置
├── tools/                     # 工具模块
│   ├── call_a2a_agent.py      # 调用 Agent 工具实现
│   ├── call_a2a_agent.yaml    # 调用 Agent 工具配置
│   ├── get_a2a_agent_information.py   # 获取 Agent 信息工具实现
│   ├── get_a2a_agent_information.yaml # 获取 Agent 信息工具配置
│   └── utils.py               # 工具函数模块
├── _assets/                   # 资源文件
│   ├── icon.png               # 插件图标
│   └── icon-dark.png          # 暗色模式图标
└── readme/                    # 说明文档
    └── README_zh_Hans.md      # 中文说明
```

---

## 模块详解

### 1. 入口模块 (`main.py`)

**功能**: 插件启动入口

```python
from dify_plugin import Plugin, DifyPluginEnv

plugin = Plugin(DifyPluginEnv(MAX_REQUEST_TIMEOUT=120))

if __name__ == '__main__':
    plugin.run()
```

**说明**:
- 创建 Dify 插件实例
- 设置最大请求超时时间为 120 秒
- 启动插件运行

---

### 2. Provider 模块 (`provider/`)

#### 2.1 Provider 配置 (`a2a_discovery.yaml`)

**功能**: 定义 Provider 身份信息和凭证配置

| 配置项 | 说明 |
|--------|------|
| **identity** | Provider 身份标识（名称、标签、描述、图标） |
| **tools** | 关联的工具列表（call_a2a_agent, get_a2a_agent_information） |
| **credentials_for_provider** | Nacos 连接凭证配置 |

**凭证配置项**:

| 凭证名称 | 类型 | 必填 | 说明 |
|----------|------|------|------|
| `nacos_addr` | text-input | 否 | Nacos 智能体注册中心地址（如：127.0.0.1:8848） |
| `nacos_username` | text-input | 否 | Nacos 用户名（认证时需要） |
| `nacos_password` | secret-input | 否 | Nacos 密码（认证时需要） |
| `nacos_accessKey` | text-input | 否 | 阿里云 AccessKey（MSE Nacos 时需要） |
| `nacos_secretKey` | secret-input | 否 | 阿里云 SecretKey（MSE Nacos 时需要） |

#### 2.2 Provider 实现 (`a2a_discovery.py`)

**功能**: 实现 Provider 凭证验证逻辑

```python
class A2aDiscoveryProvider(ToolProvider):
    def _validate_credentials(self, credentials: dict[str, Any]) -> None:
        # 验证 Nacos 连接凭证
        # 通过调用 Nacos 服务列出 Agent 卡片来验证连接
```

**核心逻辑**:
1. 获取 Nacos 连接配置（地址、用户名、密码、AccessKey、SecretKey）
2. 构建 Nacos 客户端配置
3. 调用 `list_agent_cards_by_name` 验证连接有效性
4. 失败时抛出 `ToolProviderCredentialValidationError`

---

### 3. Tools 模块 (`tools/`)

#### 3.1 工具一：获取 Agent 信息 (`get_a2a_agent_information`)

**功能**: 获取所有预配置 A2A 智能体的基础信息

**参数配置**:

| 参数名称 | 类型 | 必填 | 说明 |
|----------|------|------|------|
| `discovery_type` | select | 是 | 发现方式（nacos/url） |
| `available_agent_names` | string | 否 | Nacos 模式下的智能体名称列表（逗号分隔） |
| `available_agent_urls` | string | 否 | URL 模式下的智能体 URL 映射（JSON 格式） |
| `namespace_id` | string | 否 | Nacos 命名空间 ID（默认：public） |

**返回数据**:
```json
{
    "agents": [
        {
            "agent_name": "translator_agent",
            "description": "Agent 描述",
            "skills": [...]
        }
    ]
}
```

**工作流程**:
1. 解析配置的智能体列表
2. 遍历每个智能体获取其 AgentCard
3. 提取名称、描述、技能信息
4. 返回聚合结果

---

#### 3.2 工具二：调用 A2A Agent (`call_a2a_agent`)

**功能**: 调用指定的远程 A2A 智能体

**参数配置**:

| 参数名称 | 类型 | 必填 | 说明 |
|----------|------|------|------|
| `discovery_type` | select | 是 | 发现方式（nacos/url） |
| `available_agent_names` | string | 否 | Nacos 模式下的智能体名称列表 |
| `available_agent_urls` | string | 否 | URL 模式下的智能体 URL 映射 |
| `namespace_id` | string | 否 | Nacos 命名空间 ID |
| `target_agent` | string | 是 | 目标调用的智能体名称（LLM 选择） |
| `query` | string | 是 | 发送给智能体的消息内容 |

**返回数据**:
```json
{
    "target_agent": "translator_agent",
    "result": <A2A 响应消息>
}
```

**工作流程**:
1. 获取目标智能体的 AgentCard
2. 创建 A2A 客户端配置（非流式、非轮询）
3. 构建消息对象（Message with TextPart）
4. 通过 A2A 客户端发送消息
5. 接收并返回响应

---

#### 3.3 工具函数模块 (`utils.py`)

**功能**: 提供公共工具函数

**主要函数**:

| 函数名 | 功能 |
|--------|------|
| `parse_available_agents_nacos()` | 解析逗号分隔的 Agent 名称列表 |
| `parse_available_agents_url()` | 解析 JSON 格式的 Agent URL 映射 |
| `get_agent_names_list()` | 根据发现方式获取 Agent 名称列表 |
| `validate_target_agent()` | 验证目标 Agent 是否在可用列表中 |
| `get_a2a_agent_card()` | 获取单个 Agent 的 AgentCard |
| `get_target_agent_card()` | 从多 Agent 配置中获取目标 Agent 的 AgentCard |
| `get_all_agents_info()` | 获取所有配置 Agent 的信息 |
| `get_agent_card_from_url()` | 通过 URL 直接获取 AgentCard |

**关键逻辑**:
- **Nacos 模式**: 通过 `NacosAIMaintainerService` 从 Nacos 注册中心获取 AgentCard
- **URL 模式**: 通过 HTTP 请求直接访问 `/.well-known/agent.json` 获取 AgentCard

---

### 4. 插件清单 (`manifest.yaml`)

**功能**: 定义插件元数据和资源配置

```yaml
version: 0.0.1
type: plugin
author: nacos
name: a2a_discovery
resource:
  memory: 268435456        # 256MB 内存
  permission:
    storage:
      enabled: true
      size: 1048576        # 1MB 存储
plugins:
  tools:
    - provider/a2a_discovery.yaml
meta:
  runner:
    language: python
    version: "3.12"
    entrypoint: main
```

---

## 依赖说明

| 依赖包 | 版本 | 说明 |
|--------|------|------|
| `dify_plugin` | >=0.4.0,<0.7.0 | Dify 插件 SDK |
| `nacos-maintainer-sdk-python` | ==0.5.1 | Nacos AI 维护者 SDK |

**间接依赖**:
- `a2a` - A2A 协议客户端库
- `httpx` - 异步 HTTP 客户端
- `pydantic` - 数据验证库

---

## 使用场景

### 场景一：Nacos 注册中心模式

适用于企业级部署，所有 A2A Agent 注册到 Nacos 统一管理：

1. 配置 Nacos 连接凭证
2. 设置 `discovery_type = "nacos"`
3. 配置 `available_agent_names = "agent1,agent2,agent3"`
4. 调用 `get_a2a_agent_information` 获取所有 Agent 信息
5. 调用 `call_a2a_agent` 执行具体任务

### 场景二：直接 URL 模式

适用于小规模或测试场景，直接通过 URL 访问 Agent：

1. 设置 `discovery_type = "url"`
2. 配置 `available_agent_urls = {"agent1":"http://host1:port/.well-known/agent.json"}`
3. 调用工具执行任务

---

## 工作流程图

```
用户请求
    │
    ▼
┌─────────────────────────────┐
│  get_a2a_agent_information  │  ← 获取可用 Agent 列表
└─────────────────────────────┘
    │
    ▼
┌─────────────────────────────┐
│     解析 discovery_type     │
│    (nacos / url)            │
└─────────────────────────────┘
    │
    ├───── nacos ─────┐
    │                 │
    ▼                 ▼
┌───────────┐   ┌───────────┐
│  Nacos    │   │   HTTP    │
│  Registry │   │   Direct  │
└───────────┘   └───────────┘
    │                 │
    └────────┬────────┘
             │
             ▼
┌─────────────────────────────┐
│     返回 AgentCard 信息      │
│  (name, description, skills)│
└─────────────────────────────┘
    │
    ▼
┌─────────────────────────────┐
│     call_a2a_agent          │  ← 调用选定的 Agent
│     (target_agent, query)   │
└─────────────────────────────┘
    │
    ▼
┌─────────────────────────────┐
│     A2A 协议通信             │
│     (Message/Task/Event)    │
└─────────────────────────────┘
    │
    ▼
用户获得结果
```

---

## 总结

这是一个完整的 **A2A Agent 客户端插件**，为 Dify 平台提供了与 A2A 智能体交互的能力：

| 特性 | 说明 |
|------|------|
| **双模式发现** | 支持 Nacos 注册中心和直接 URL 两种方式 |
| **多 Agent 支持** | 可配置多个 Agent，LLM 智能选择 |
| **完整信息获取** | 获取 Agent 描述、技能等元信息 |
| **标准 A2A 协议** | 遵循 A2A 标准通信协议 |
| **企业级支持** | 支持 Nacos 认证、阿里云 MSE |
| **错误处理** | 完善的异常处理和验证机制 |