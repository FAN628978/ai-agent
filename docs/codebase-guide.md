# 代码详细说明

本文说明当前代码如何组织、运行链路如何串起来，以及后续开发应优先修改哪些位置。它描述的是当前实现状态，不是完整架构蓝图。

## 总体入口

项目包名是 `agent_system`，命令行入口在 `pyproject.toml` 中声明：

```toml
[project.scripts]
agent-system = "agent_system.api.cli:main"
```

用户通常通过 CLI 进入系统：

- `agent-system plan "任务"`：创建计划后停止。
- `agent-system run "任务"`：创建计划并执行。
- `agent-system runtime-chat`：每轮先经过 `AgentRuntime`，再整理成 Assistant 回复。

## 目录职责

```text
src/agent_system/
├── agents/       Planner 和 Reflector
├── api/          Typer CLI
├── config/       YAML 配置模型和加载
├── context/      Planner 上下文拼装和预算
├── execution/    Plan Step 执行器
├── llm/          OpenAI-compatible LLM Client
├── models/       Runtime 数据协议
├── observability/ 结构化日志
├── prompts/      Prompt Registry 和模板
├── runtime/      AgentRuntime、工厂、checkpoint
├── skills/       能力元数据注册
└── tools/        工具协议、注册、路由、内置工具
```

## 核心运行链路

ACT 模式的主链路是：

```text
CLI -> UserRequest -> create_runtime_from_config()
    -> AgentRuntime.run()
    -> PlannerAgent.make_plan()
    -> Executor.execute()
    -> ToolRouter.invoke()
    -> Reflector.evaluate()
    -> AgentEvent stream
```

PLAN 模式的链路类似，但 `AgentRuntime` 在 `plan.created` 后输出 `run.waiting_for_approval` 并停止，不执行工具。

## 数据模型

核心协议集中在 `src/agent_system/models/`。

### UserRequest

位置：`models/request.py`

表示用户的一次请求：

- `session_id`：会话 ID。
- `user_id`：用户 ID。
- `workspace_id`：工作区路径或标识。
- `content`：用户输入。
- `mode`：运行模式，默认 `act`。
- `attachments`：附件路径列表，当前未深入使用。
- `metadata`：扩展字段。

`RunMode` 当前支持：

- `ask`
- `plan`
- `act`
- `review`
- `background`

### Plan / Step / Critique

位置：`models/planning.py`

`Plan` 是 Planner 输出：

- `goal`：整体目标。
- `mode`：运行模式。
- `steps`：步骤列表。
- `assumptions`：假设。
- `risks`：风险。

`Step` 是可执行单元：

- `id`、`title`、`objective`
- `depends_on`
- `suggested_tools`
- `tool_calls`
- `risk`
- `acceptance`

`Critique` 是 Reflector 输出：

- `done`：任务是否完成。
- `confidence`：置信度。
- `issues`：问题列表。
- `next_action`：`finish`、`retry`、`replan`、`ask_user`。

### ToolCall / ToolResult

位置：`models/tools.py`

`ToolCall` 是结构化工具调用：

- `id`
- `name`
- `arguments`
- `timeout_s`
- `requires_approval`

`ToolResult` 是统一工具返回：

- `call_id`
- `name`
- `ok`
- `content`
- `error`
- `metadata`

### AgentState / AgentEvent

位置：`models/runtime.py`、`models/events.py`

`AgentState` 保存单次任务运行状态：

- `session_id`
- `task_id`
- `mode`
- `plan`
- `completed_steps`
- `tool_results`
- `iteration`
- `max_iterations`

`AgentEvent` 是 Runtime 对外输出的事件：

- `type`
- `data`

当前常见事件：

- `run.started`
- `plan.created`
- `run.waiting_for_approval`
- `execution.completed`
- `reflection.completed`
- `run.completed`
- `run.needs_user_input`
- `run.stopped`

## Runtime

### AgentRuntime

位置：`runtime/loop.py`

`AgentRuntime.run()` 是核心异步生成器，输入 `UserRequest`，输出 `AgentEvent`。

执行流程：

1. 创建 `AgentState` 和 `task_id`。
2. 输出 `run.started`。
3. 保存 checkpoint。
4. 如果还没有 plan，调用 `PlannerAgent.make_plan()`。
5. 输出 `plan.created`。
6. 如果是 PLAN 模式，输出 `run.waiting_for_approval` 后停止。
7. 调用 `Executor.execute()`。
8. 把工具结果写入 `state.tool_results`。
9. 输出 `execution.completed`。
10. 调用 `Reflector.evaluate()`。
11. 输出 `reflection.completed`。
12. 如果完成，输出 `run.completed`。
13. 如果需要用户输入，输出 `run.needs_user_input`。
14. 达到最大迭代次数后输出 `run.stopped`。

当前 `AgentRuntime` 还没有真正的 Session Store，多轮对话状态仍主要由 CLI 拼接。

### create_runtime_from_config

位置：`runtime/factory.py`

这个函数把配置、LLM、工具、skills、context 和 runtime 串起来。

它会：

1. 加载 `AppConfig`。
2. 注册六个核心工具：
   - `Read`
   - `Write`
   - `Edit`
   - `Grep`
   - `Glob`
   - `Bash`
3. 根据 `permissions.default_shell` 决定 `Bash` 是否启用。
4. 注册默认 skills：
   - `coding`
   - `runtime`
   - `review`
5. 创建 `ContextAssembler`，注入工具 schema、skills schema、workspace。
6. 如果 provider 是 `openai-compatible`，创建 `OpenAICompatibleClient` 并注入 Planner。
7. 创建 `ToolRouter` 和 `Executor`。
8. 返回 `AgentRuntime`。

## Observability

位置：`observability/logging.py`

当前实现 `JsonlEventLogger`，默认通过 `configs/default.yaml` 写入：

```text
logs/agent-system.jsonl
```

记录内容：

- Runtime 事件类型、时间戳、session_id、task_id、user_id、workspace_id。
- `plan.created` 只记录 goal、mode、step_count、risk_count。
- `execution.completed` 不记录完整 `tool_results`，只保留执行摘要。
- `reflection.completed` 只记录 done、confidence、next_action、issue_count。

第一版不做日志轮转、OpenTelemetry、metrics 或 trace 查询。

### Checkpoint

位置：`runtime/checkpoint.py`

当前只有 `InMemoryCheckpointStore`，按 `task_id` 保存 `AgentState`。它只用于当前进程内测试和基础恢复，不具备持久化能力。

## Planner

位置：`agents/planner.py`

`PlannerAgent` 只支持 LLM Planner 路径。没有 LLM client 时会直接报错，不再提供规则 Planner 兜底。

LLM Planner 的流程：

1. 调用 `ContextAssembler.planner_messages()` 生成 messages。
2. 调用 `llm_client.chat()`。
3. 从回复中提取 JSON 对象。
4. 规范化常见字段：
   - `goal`
   - `assumptions`
   - `risks`
   - `steps`
   - `tool_calls`
5. 如果 plan 没有任何 `suggested_tools` 或 `tool_calls`，会要求 LLM 基于工具 schema 重新判断是否需要工具。
6. 用 Pydantic 校验成 `Plan`。

如果 LLM 输出不是 JSON 或字段不可用，会直接暴露错误，不再回退到规则计划。

## Executor

位置：`execution/executor.py`

`Executor.execute()` 顺序执行 `Plan.steps`。

执行规则：

1. 已在 `state.completed_steps` 的 step 会跳过。
2. 如果 step 有 `tool_calls`，优先执行结构化工具调用。
3. 如果没有 `tool_calls`，再从 `suggested_tools` 推断参数。
4. 如果没有可执行工具，step 会失败，不会被模拟完成。
5. 只要工具全部成功，step 标记为完成。
6. 工具失败时 step 失败，不写入 completed。

当前 Executor 不做：

- DAG 并发。
- 依赖排序。
- LLM 驱动执行。
- 权限审批事件。
- 自动重试。

## Reflector

位置：`agents/reflector.py`

当前 Reflector 是简化实现，不调用 LLM。它根据执行结果判断是否完成：

- 所有 step 成功时，`done=True`。
- 存在失败 step 时，`done=False`，并要求后续动作。

后续要做 LLM 驱动的 Reflector，应保持 `Critique` 输出协议不变。

## 工具系统

工具系统位于 `tools/`。

### ToolSchema / ToolPermission

位置：`tools/schemas.py`

`ToolSchema` 描述工具能力：

- `name`
- `description`
- `input_schema`
- `risk`
- `permission`
- `read_only`
- `cache_ttl_s`

`ToolPermission` 描述权限需求：

- `filesystem`
- `shell`
- `network`
- `approval_required`

当前权限信息主要是元数据，还没有完整策略引擎。

### BaseTool / ToolContext / Workspace

位置：`tools/base.py`

`BaseTool` 是工具基类：

- 每个工具提供 `schema`。
- 每个工具实现 `run(arguments, context)`。

`Workspace` 负责把相对路径解析到工作区内，并阻止路径越界。

### ToolRegistry

位置：`tools/registry.py`

保存工具实例：

- `register(tool)`
- `get(name)`
- `schemas(read_only=None)`

重复注册同名工具会抛 `ValueError`。

### ToolRouter

位置：`tools/router.py`

根据 `ToolCall.name` 找到工具并执行。

错误处理：

- 未知工具返回 `ToolResult(ok=False, error="unknown tool: ...")`。
- 工具内部异常会被捕获并转成失败 `ToolResult`。

当前 `ToolRouter` 还没有接入完整权限审批逻辑。

### 内置工具

位置：`tools/builtin/`

当前内置六个核心工具：

- `Read`：读取工作区内文件。
- `Write`：新建或覆盖工作区内文件。
- `Edit`：替换已有文件中的文本。
- `Grep`：在工作区内搜索文本。
- `Glob`：按路径模式查找文件或目录。
- `Bash`：执行 shell 命令，默认禁用。

`Bash` 是否启用由 `configs/default.yaml` 的 `permissions.default_shell` 决定。默认是 `deny`。

## LLM Client

位置：`llm/client.py`

当前只有 `OpenAICompatibleClient`，使用标准库 `urllib` 调用 OpenAI-compatible 接口。

支持：

- `list_models()`：请求 `/v1/models`。
- `chat(messages, max_tokens, temperature)`：请求 `/v1/chat/completions`。

返回模型：

- `ChatMessage`
- `ChatResponse`

默认配置在 `configs/default.yaml`：

- `base_url: http://localhost:8500`
- `chat: MiniMax-M2.5`
- `planner: MiniMax-M2.5`

## Context 与 Prompt

### PromptRegistry

位置：`prompts/registry.py`

负责从模板目录读取 markdown prompt，并用 `string.Template` 渲染变量。

模板目录：

```text
src/agent_system/prompts/templates/
├── system.md
├── planner.md
└── reflector.md
```

### ContextAssembler

位置：`context/assembler.py`

`ContextAssembler.planner_messages()` 负责组装给 Planner LLM 的 messages。

当前注入内容：

- system prompt。
- planner prompt。
- 可用 tool schemas。
- 可用 skill schemas。
- workspace。
- 用户请求内容。

当前还没有注入：

- session summary。
- memory。
- 文件索引。
- 最近工具结果摘要。

### TokenBudget

位置：`context/budget.py`

当前是字符级预算控制，用于限制注入到 prompt 的工具和 skills schema 长度。它不是严格 token 计数器。

## Skills

位置：`skills/`

Skills 当前是能力元数据层，不直接执行动作。

核心类：

- `SkillSchema`
- `BaseSkill`
- `SkillRegistry`

默认内置 skills：

- `coding`
- `runtime`
- `review`

这些 skills 会由 `create_runtime_from_config()` 注册，然后注入 Planner Context，让模型知道当前系统偏向哪些能力、触发词、建议工具和 prompt hints。

## Config

位置：`config/`

`models.py` 定义：

- `RuntimeConfig`
- `ModelConfig`
- `ContextConfig`
- `PermissionsConfig`
- `MemoryConfig`
- `AppConfig`

`loader.py` 提供：

- `load_config(path="configs/default.yaml")`

配置文件使用 YAML。当前配置重点控制：

- runtime 默认模式和最大迭代次数。
- MiniMax OpenAI-compatible 模型地址和模型名。
- context 预算。
- shell/network 默认权限。
- memory 开关。
- logging 开关和 JSONL 文件路径。

## CLI

位置：`api/cli.py`

CLI 使用 Typer 和 Rich。

### run

`agent-system run "任务"`

创建 ACT 模式 `UserRequest`，调用 `_run_request()`，打印 Runtime 事件。

常用参数：

- `--config`
- `--json`
- `--show-tool-results`
- `--user-id`
- `--workspace-id`

### plan

`agent-system plan "任务"`

创建 PLAN 模式 `UserRequest`，只生成 plan，不执行工具。

### runtime-chat

`agent-system runtime-chat`

每轮用户输入都会：

1. 先处理 runtime-chat 斜杠命令。
2. 普通输入会调用 `AgentRuntime`。
3. 根据 Runtime events 生成 fallback answer。
4. 对成功工具结果，用 Chat LLM 合成最终回复。

支持的斜杠命令：

- `/help`：查看可用命令。
- `/clear`：清空当前 CLI 本地回复历史。
- `/tools`：查看当前 Runtime 可用工具。
- `/exit`、`/quit`：退出对话。

当前限制：

- LLM 回复合成历史仍主要在 CLI 层维护。
- `/clear` 不清理 Runtime 内部 session 状态。

## 测试结构

测试位于 `tests/`。

```text
tests/
├── integration/
│   ├── test_minimax_local.py
│   └── test_minimax_runtime.py
├── unit/
│   ├── agents/
│   ├── api/
│   ├── config/
│   ├── context/
│   ├── execution/
│   ├── llm/
│   ├── models/
│   ├── prompts/
│   ├── runtime/
│   ├── skills/
│   └── tools/
└── test_import.py
```

默认测试：

```bash
uv run pytest
```

当前本地结果：

```text
50 passed, 2 skipped
```

MiniMax 集成测试默认跳过，需要显式启用：

```powershell
$env:AGENT_SYSTEM_RUN_LOCAL_LLM_TESTS='1'
$env:AGENT_SYSTEM_LLM_BASE_URL='http://localhost:8500'
$env:AGENT_SYSTEM_LLM_MODEL='MiniMax-M2.5'
uv run pytest tests\integration
```

## 新增功能时的落点

### 新增工具

建议修改：

1. 在 `tools/builtin/` 新增工具类。
2. 在 `tools/builtin/__init__.py` 导出。
3. 在 `runtime/factory.py` 注册。
4. 如果 Planner 需要知道参数格式，更新 `prompts/templates/planner.md`。
5. 增加 `tests/unit/tools/` 和必要的 executor 测试。

### 新增运行状态

建议修改：

1. `models/runtime.py`
2. `runtime/loop.py`
3. `runtime/checkpoint.py` 或新增 `runtime/session.py`
4. `tests/unit/runtime/`

下一步的 Session Store 应该从这里开始。

### 新增 Planner 上下文

建议修改：

1. `context/assembler.py`
2. `context/budget.py`
3. `prompts/templates/planner.md`
4. `tests/unit/context/`

### 接入新的 LLM Provider

建议修改：

1. `llm/` 新增 provider 或扩展 client 抽象。
2. `config/models.py` 增加 provider 配置。
3. `runtime/factory.py` 根据 provider 创建 client。
4. 增加 `tests/unit/llm/`。

### 做权限审批

建议修改：

1. `tools/schemas.py`
2. `tools/router.py`
3. `runtime/loop.py`
4. `models/events.py` 或直接扩展事件 data。
5. `execution/executor.py`
6. `tests/unit/tools/`、`tests/unit/runtime/`

第一版应优先让高风险工具返回审批需求事件，而不是直接执行。

## 当前主要限制

- Runtime 没有真正的多轮 Session Store。
- Memory 系统还没实现。
- Reflector 不是 LLM 驱动。
- Executor 不做复杂执行策略和重试。
- ToolRouter 还没有完整权限审批。
- MCP / 插件化工具没有实现。
- 没有 Web UI、SSE、WebSocket 或持久化运行记录。

这些限制对应 `docs/next-development.md` 中的后续大模块清单。
