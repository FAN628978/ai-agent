# Codex 项目指引

## 个人偏好

请称呼用户为 **Haitao**。

## 代码修改原则

1. 以需求为准：严格按照指示修改代码，不擅自改动无关内容。
2. 最小改动：只在必要范围内修改，保持原有代码结构、命名和逻辑。
3. 避免重构：不因顺手优化而进行大规模重构。
4. 分离建议与修改：先完成需求，再补充可选改进建议，不混入本次修改中。
5. 说明影响：对每处修改说明原因和影响范围。

## 不明确时的处理

- 优先基于现有代码做最小改动实现。
- 不自行大幅扩展需求。
- 如需确认，主动提问。

## 项目概览

本项目目标是实现一个面向生产级场景的 Python AI Agent Runtime。

核心闭环：

```text
用户请求 -> 上下文组装 -> Planner 生成计划 -> Executor 执行工具 -> Reflector 校验结果 -> 输出响应
```

当前项目仍处于早期工程化阶段，已完成基础 Python 工程骨架、核心数据模型、最小 Runtime 主循环、本地 MiniMax 2.5 Planner / Chat LLM 接入、ChatGPT 式 CLI、Runtime 对话入口、工具系统到 Runtime Executor 的接入、结构化 ToolCall 执行，以及 Prompt Registry / Planner Context 组装。当前还没有实现多 Agent 能力或 LLM 驱动的 Reflector / Executor。

## 重要文档

| 文件 | 说明 |
| --- | --- |
| `AI_AGENT_ARCHITECTURE.md` | 完整架构设计方案 |
| `DEVELOPMENT_PLAN.md` | 分阶段开发计划 |
| `NEXT_DEVELOPMENT.md` | 下一步开发建议：Runtime 多轮任务状态 |
| `PROJECT.md` | 项目状态和交接说明 |
| `README.md` | 项目简介、安装方式、测试命令 |

## 当前进展

### Phase 0：项目初始化

状态：已完成。

已交付：

- `pyproject.toml`
- `README.md`
- `configs/default.yaml`
- `src/agent_system/__init__.py`
- `tests/test_import.py`
- `.gitignore`
- `PROJECT.md`
- `AGENTS.md`

验证结果：

```text
uv run pytest
46 passed, 2 skipped
```

### Phase 1：核心数据模型

状态：已完成。

已交付：

- `src/agent_system/models/request.py`
- `src/agent_system/models/planning.py`
- `src/agent_system/models/tools.py`
- `src/agent_system/models/runtime.py`
- `src/agent_system/models/events.py`
- `src/agent_system/models/__init__.py`
- `tests/unit/models/test_core_models.py`

已实现：

- `RunMode`
- `UserRequest`
- `Step`
- `Plan`
- `ToolCall`
- `ToolResult`
- `Critique`
- `AgentState`
- `AgentEvent`

验证结果：

```text
uv run pytest
46 passed, 2 skipped
```

### Phase 2：Runtime 主循环

状态：已完成。

已交付：

- `src/agent_system/runtime/loop.py`
- `src/agent_system/runtime/checkpoint.py`
- `src/agent_system/runtime/__init__.py`
- `src/agent_system/agents/planner.py`
- `src/agent_system/agents/reflector.py`
- `src/agent_system/agents/__init__.py`
- `src/agent_system/execution/executor.py`
- `src/agent_system/execution/__init__.py`
- `tests/unit/runtime/test_runtime_loop.py`

已实现：

- `AgentRuntime`
- 规则版 `PlannerAgent`
- 顺序执行版 `Executor`
- 简化版 `Reflector`
- 内存版 `InMemoryCheckpointStore`
- `StepResult`
- `ExecutionResult`

验证结果：

```text
uv run pytest
46 passed, 2 skipped
```

### ChatGPT 式 CLI

状态：已完成。

已交付：

- `src/agent_system/api/cli.py`
- `src/agent_system/api/__init__.py`
- `tests/unit/api/test_cli.py`
- `pyproject.toml` 中的 `agent-system` 命令入口

已支持：

- `agent-system run "任务内容"`
- `agent-system plan "任务内容"`
- `agent-system chat`
- `agent-system runtime-chat`
- `--config`
- `--no-llm`
- `--json`
- `--show-reasoning`

说明：

- 默认使用 `configs/default.yaml` 中配置的 MiniMax Planner。
- `agent-system chat` 会直接调用 `model.chat`，保留当前会话上下文历史，并只输出 Assistant 回复。
- `agent-system chat` 默认隐藏 `<think>...</think>` 内容，可用 `--show-reasoning` 显示。
- `agent-system runtime-chat` 每轮都会经过 `AgentRuntime`，再把事件和工具结果整理成 Assistant 回复。
- `--no-llm` 可切换到规则 Planner。
- 当前 Executor 已能执行明确建议的内置工具；没有工具建议的步骤仍会走 mock 执行。

验证结果：

```text
uv run pytest
46 passed, 2 skipped

uv run agent-system plan "为项目生成一个下一步开发计划" --json
成功通过 MiniMax 生成 plan.created 事件
```

### 本地 MiniMax 2.5 接入

状态：已接入默认配置和 Runtime 工厂。

本地服务：

```text
http://localhost:8500
```

模型：

```text
MiniMax-M2.5
```

已交付：

- `configs/default.yaml` 中的 MiniMax 配置
- `src/agent_system/config/models.py`
- `src/agent_system/config/loader.py`
- `src/agent_system/config/__init__.py`
- `src/agent_system/llm/client.py`
- `src/agent_system/llm/__init__.py`
- `src/agent_system/runtime/factory.py`
- `tests/unit/config/test_config_loader.py`
- `tests/unit/runtime/test_runtime_factory.py`
- `tests/unit/agents/test_planner_agent.py`
- `tests/unit/llm/test_openai_compatible_client.py`
- `tests/integration/test_minimax_local.py`
- `tests/integration/test_minimax_runtime.py`

说明：

- 该 client 兼容 OpenAI 风格 `/v1/models` 和 `/v1/chat/completions`。
- `configs/default.yaml` 默认指向 `http://localhost:8500` 和 `MiniMax-M2.5`。
- `create_runtime_from_config()` 会按配置创建带 LLM client 的 `PlannerAgent`。
- `PlannerAgent` 会优先使用 LLM 生成 `Plan`，LLM 输出不可解析时回退到规则计划。
- 默认测试会跳过真实本地服务测试。

验证结果：

```text
uv run pytest
46 passed, 2 skipped

AGENT_SYSTEM_RUN_LOCAL_LLM_TESTS=1 uv run pytest tests/integration
2 passed
```

### Phase 3：工具系统

状态：已完成。

已交付：

- `src/agent_system/tools/base.py`
- `src/agent_system/tools/schemas.py`
- `src/agent_system/tools/registry.py`
- `src/agent_system/tools/router.py`
- `src/agent_system/tools/__init__.py`
- `src/agent_system/tools/builtin/file.py`
- `src/agent_system/tools/builtin/grep.py`
- `src/agent_system/tools/builtin/shell.py`
- `src/agent_system/tools/builtin/__init__.py`
- `tests/unit/tools/test_tool_system.py`

已实现：

- `BaseTool`
- `ToolSchema`
- `ToolPermission`
- `ToolRegistry`
- `ToolRouter`
- `Workspace`
- `ToolContext`
- `file.read`
- `file.write`
- `grep.search`
- `shell.run`

说明：

- 工具可以注册、查询和调用。
- 工具统一返回 `ToolResult`。
- 文件工具限制在 workspace 内，阻止路径越界。
- `grep.search` 支持正则搜索文本文件。
- `shell.run` 默认禁用，显式启用后支持超时、stdout、stderr 和 returncode。
- 当前工具系统已接入 `Executor` 的保守路径；只有 Step 明确列出内置工具名时才会调用工具。

验证结果：

```text
uv run pytest
46 passed, 2 skipped
```

### 结构化 ToolCall 规划与展示

状态：已完成。

已交付：

- `Step.tool_calls`
- Planner Prompt 中的 `tool_calls` 生成要求
- Planner 对 LLM `tool_calls` 输出的规范化
- Executor 优先执行 `step.tool_calls`
- `agent-system run --show-tool-results`
- `tests/unit/execution/test_executor_tools.py` 中的结构化 ToolCall 覆盖
- `tests/unit/api/test_cli.py` 中的工具结果展示覆盖

说明：

- Planner 可以产出结构化 `ToolCall`，减少从自然语言 objective 猜参数。
- Executor 优先执行 `step.tool_calls`，没有结构化调用时才回退到 `suggested_tools + objective` 推断。
- JSON 事件中保留完整 `tool_results`，方便脚本消费。
- 普通 CLI 输出默认隐藏完整工具结果，`--show-tool-results` 显示摘要。

验证结果：

```text
uv run pytest
46 passed, 2 skipped
```

### 上下文与 Prompt Registry

状态：已完成。

已交付：

- `src/agent_system/prompts/registry.py`
- `src/agent_system/prompts/templates/system.md`
- `src/agent_system/prompts/templates/planner.md`
- `src/agent_system/prompts/templates/reflector.md`
- `src/agent_system/context/assembler.py`
- `src/agent_system/context/budget.py`
- `tests/unit/prompts/test_prompt_registry.py`
- `tests/unit/context/test_context_assembler.py`

说明：

- Planner system prompt 已从 Python 代码迁移到模板文件。
- `ContextAssembler` 会拼装 system prompt、planner prompt、用户请求。
- Planner context 会注入 workspace 信息和工具 schema。
- Runtime 工厂会把已注册工具 schema 传给 Planner context。

验证结果：

```text
uv run pytest
46 passed, 2 skipped
```

### Runtime 对话入口

状态：已完成。

已交付：

- `agent-system runtime-chat`
- Runtime 事件到 Assistant 回复的渲染逻辑
- Runtime 对话历史拼接
- 可选 LLM 回复合成
- `--show-events`
- `tests/unit/api/test_cli.py` 中的 runtime-chat 覆盖

说明：

- Runtime 模式现在可以像对话一样使用。
- `runtime-chat --no-llm` 会直接展示 Runtime 工具执行结果。
- 默认 `runtime-chat` 会先跑 Runtime，再用 `model.chat` 合成自然语言回复。
- `--show-events` 可用于调试完整 Runtime 事件流。

验证结果：

```text
uv run pytest
46 passed, 2 skipped
```

## 当前目录结构

```text
.
├── AGENTS.md
├── AI_AGENT_ARCHITECTURE.md
├── DEVELOPMENT_PLAN.md
├── PROJECT.md
├── README.md
├── configs/
│   └── default.yaml
├── pyproject.toml
├── src/
│   └── agent_system/
│       ├── __init__.py
│       ├── api/
│       │   ├── __init__.py
│       │   └── cli.py
│       ├── agents/
│       │   ├── __init__.py
│       │   ├── planner.py
│       │   └── reflector.py
│       ├── execution/
│       │   ├── __init__.py
│       │   └── executor.py
│       ├── llm/
│       │   ├── __init__.py
│       │   └── client.py
│       └── models/
│           ├── __init__.py
│           ├── events.py
│           ├── planning.py
│           ├── request.py
│           ├── runtime.py
│           └── tools.py
│       └── runtime/
│           ├── __init__.py
│           ├── checkpoint.py
│           └── loop.py
└── tests/
    ├── test_import.py
    └── unit/
        ├── api/
        │   └── test_cli.py
        ├── llm/
        │   └── test_openai_compatible_client.py
        ├── models/
        │   └── test_core_models.py
        └── runtime/
            └── test_runtime_loop.py
    └── integration/
        └── test_minimax_local.py
```

## 当前技术选择

- Python：`>=3.11`
- 构建后端：`hatchling`
- 运行依赖：
  - `pydantic`
  - `pyyaml`
  - `rich`
  - `typer`
- 开发依赖：
  - `pytest`

## 下一步任务

下一步建议继续完善权限策略和工具调用审批。

如果优先关注 Agent 主体能力，见 `NEXT_DEVELOPMENT.md`，建议先做 Runtime 多轮任务状态。

建议实现：

- 将 `permissions.default_shell` 和 ToolPermission 检查接入 `ToolRouter`。
- 高风险工具返回审批需求事件，而不是直接执行。
- 增加工具调用审计记录，包括 call_id、tool name、arguments 摘要、结果状态。
- 保持 `shell.run` 默认禁用，启用需显式配置。

验收标准：

- 低风险工具可自动执行。
- 高风险工具不会无审批执行。
- 工具调用失败和拒绝都有结构化结果。
- Shell 默认禁用，启用需显式配置。
- `uv run pytest` 通过。

## 暂不处理事项

第一版暂不实现：

- 真实 LLM 调用
- 多 Agent Supervisor
- MCP Server
- Memory Manager
- 向量数据库
- Web UI
- Temporal / Redis / Kafka
- 复杂权限系统
- 分布式 Worker

## 常用命令

运行测试：

```bash
uv run pytest
```

运行 CLI：

```powershell
uv run agent-system plan "为项目生成一个下一步开发计划"
uv run agent-system run "帮我分析当前项目"
uv run agent-system chat
```

运行本地 MiniMax 集成测试：

```powershell
$env:AGENT_SYSTEM_RUN_LOCAL_LLM_TESTS='1'
$env:AGENT_SYSTEM_LLM_BASE_URL='http://localhost:8500'
$env:AGENT_SYSTEM_LLM_MODEL='MiniMax-M2.5'
uv run pytest tests\integration
```

查看项目文件：

```bash
rg --files
```

## 接手建议

后续 Codex Agent 接手时建议按以下顺序阅读：

1. 先读 `AGENTS.md`，了解项目规则和当前状态。
2. 再读 `DEVELOPMENT_PLAN.md`，确认下一阶段任务。
3. 需要架构细节时读 `AI_AGENT_ARCHITECTURE.md`。
4. 编码前用 `rg --files` 查看实际文件状态。
5. 完成修改后运行 `uv run pytest`。
