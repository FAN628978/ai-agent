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
├── agents/         Planner、Reasoner、Reflector
├── api/            Typer CLI
├── config/         YAML 配置模型和加载
├── context/        Planner 上下文拼装和预算
├── execution/      Plan Step 执行器
├── llm/            OpenAI-compatible LLM Client
├── models/         Runtime 数据协议
├── observability/  结构化日志
├── prompts/        Prompt Registry 和模板
├── runtime/        AgentRuntime、工厂、checkpoint、session
├── skills/         能力元数据注册
└── tools/          工具协议、注册、路由、内置工具
```

## 核心运行链路

ACT 模式当前主链路是：

```text
CLI -> UserRequest -> create_runtime_from_config()
    -> AgentRuntime.run()
    -> InMemorySessionStore.get(session_id)
    -> SessionRecord.context_summary()
    -> PlannerAgent.make_plan()
    -> Executor.execute()
    -> ToolRouter.invoke()
    -> AgentReasoner.next_action() 或 Reflector.evaluate()
    -> AgentEvent stream
    -> SessionRecord.record_run()
    -> InMemorySessionStore.save(session)
```

PLAN 模式的链路类似，但 `AgentRuntime` 在 `plan.created` 后输出 `run.waiting_for_approval` 并停止，不执行工具。

如果运行中出现工具审批需求，Runtime 会输出 `run.waiting_for_tool_approval` 并停止等待后续处理。当前还没有实现 `/approve`、`/deny` 和 resume。

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

- `id`
- `title`
- `objective`
- `depends_on`
- `suggested_tools`
- `tool_calls`
- `risk`
- `acceptance`

说明：`depends_on` 字段已经存在，但当前 Executor 还没有真正做依赖排序。

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
- `approved`

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
- `run.waiting_for_tool_approval`
- `reasoning.completed`
- `answer.created`
- `reflection.completed`
- `run.completed`
- `run.needs_user_input`
- `run.stopped`

## Runtime

### AgentRuntime

位置：`runtime/loop.py`

`AgentRuntime.run()` 是核心异步生成器，输入 `UserRequest`，输出 `AgentEvent`。

当前执行流程：

1. 根据 `request.session_id` 读取 session。
2. 创建 `AgentState` 和 `task_id`。
3. 输出 `run.started`。
4. 保存 checkpoint。
5. 如果还没有 plan，调用 `PlannerAgent.make_plan(request, session_context=session.context_summary())`。
6. 输出 `plan.created`。
7. 如果是 PLAN 模式，输出 `run.waiting_for_approval` 后停止。
8. 调用 `Executor.execute()`。
9. 把工具结果写入 `state.tool_results`。
10. 输出 `execution.completed`。
11. 检查工具审批请求；如有则输出 `run.waiting_for_tool_approval` 并写回 session 后停止。
12. 如果配置了 `reasoner`，调用 `AgentReasoner.next_action()`。
13. 如果 Reasoner 返回 final answer，输出 `answer.created` 和 `run.completed`。
14. 如果 Reasoner 返回 tool calls，则生成新的单步 plan 并继续循环。
15. 如果没有 Reasoner，则调用 `Reflector.evaluate()`。
16. Reflector 判断完成后输出 `run.completed`，否则根据结果输出 `run.needs_user_input` 或继续。
17. 达到最大迭代次数后输出 `run.stopped`。
18. 在完成、停止、等待审批、需要用户输入等路径写回 session。

### create_runtime_from_config

位置：`runtime/factory.py`

这个函数把配置、LLM、工具、skills、context、permission policy、executor、reasoner 和 runtime 串起来。

它会：

1. 加载 `AppConfig`。
2. 注册六个核心工具：
   - `Read`
   - `Write`
   - `Edit`
   - `Grep`
   - `Glob`
   - `Bash`
3. 根据 `permissions.default_shell != "deny"` 决定 `BashTool(enabled=...)`。
4. 注册默认 skills：
   - `coding`
   - `runtime`
   - `review`
5. 创建 `ContextAssembler`，注入工具 registry、skills schema 和 workspace。
6. 创建 Planner LLM client，并注入 `PlannerAgent`。
7. 创建 Reasoner LLM client，并注入 `AgentReasoner`。
8. 创建 `ToolPermissionPolicy`。
9. 创建 `ToolRouter` 和 `Executor`。
10. 如果启用 logging，创建 `JsonlEventLogger`。
11. 返回 `AgentRuntime`。

注意：当前工厂没有显式传入持久化 session store，因此默认使用 `InMemorySessionStore`。

## Session

位置：`runtime/session.py`

当前已经实现第一版内存 Session。

### SessionRecord

保存内容：

- `session_id`
- `messages`
- `recent_events`
- `recent_tool_results`
- `recent_plan`
- `summary`

核心方法：

- `context_summary(max_chars=MAX_CONTEXT_CHARS)`：生成给 Planner / Reasoner 使用的上下文摘要。
- `record_run(request, events, plan, tool_results)`：把本轮运行写回 session。

`context_summary()` 会包含：

- 会话摘要。
- 上一次 plan 摘要。
- 最近工具结果摘要。

为避免 prompt 过长，工具结果会被压缩：

- `Read` 只保留内容片段。
- `Glob` 保留匹配路径摘要。
- `Grep` 保留匹配行摘要。

### InMemorySessionStore

接口：

```python
async def get(self, session_id: str) -> SessionRecord
async def save(self, session: SessionRecord) -> None
```

当前限制：

- 只在当前进程内有效。
- 进程退出后丢失。
- 不支持 SQLite / Postgres。
- 不支持 pending approval 持久化。

## Observability

位置：`observability/logging.py`

当前实现 `JsonlEventLogger`，默认通过 `configs/default.yaml` 写入：

```text
logs/agent-system.jsonl
```

记录内容：

- Runtime 事件类型。
- 时间戳。
- session_id。
- task_id。
- user_id。
- workspace_id。
- `plan.created` 摘要。
- `execution.completed` 摘要。
- `reflection.completed` 摘要。

说明：

- `execution.completed` 不记录完整 `tool_results`，只保留执行摘要。
- 第一版不做日志轮转、OpenTelemetry、metrics、trace 查询或 replay。

### Checkpoint

位置：`runtime/checkpoint.py`

当前只有 `InMemoryCheckpointStore`，按 `task_id` 保存 `AgentState`。

它只用于当前进程内测试和基础恢复，不具备持久化能力。

## Planner

位置：`agents/planner.py`

`PlannerAgent` 当前以 LLM Planner 为主，并保留保守规则兜底。

流程：

1. 调用 `ContextAssembler.planner_messages()` 生成 messages。
2. 调用 `llm_client.chat(..., tools=context.llm_tools())`。
3. 如果模型返回原生 `tool_calls`，直接转换为单步 Plan。
4. 如果返回普通文本，则从回复中提取 JSON plan。
5. 规范化字段：
   - `goal`
   - `assumptions`
   - `risks`
   - `steps`
   - `suggested_tools`
   - `tool_calls`
6. 如果 plan 没有任何 `suggested_tools` 或 `tool_calls`，会要求 LLM 基于工具 schema 修正。
7. 用 Pydantic 校验成 `Plan`。
8. 如果 LLM 路径整体失败，则生成保守规则 plan，并把失败原因写入 `risks`。

说明：

- 当前 Planner 不再是纯规则 Planner。
- 当前 Planner 也不是“失败直接报错”；它有 fallback。
- 但 Runtime 外部传入的自定义 planner 仍可能抛错，此时 Runtime 会输出 `run.needs_user_input`。

## Reasoner

位置：`agents/reasoner.py`

`AgentReasoner` 是观察后决策控制器。

输入：

- 当前 `UserRequest`。
- session context。
- 当前 plan。
- 已有 tool_results。
- 当前 iteration。

输出：

- `AgentAction.thought`
- `AgentAction.tool_calls`
- `AgentAction.final_answer`
- `AgentAction.needs_user_input`

流程：

1. 构造 system / tool definitions / user observation messages。
2. 调用 LLM，并传入 tool registry 的原生 tools。
3. 如果模型返回原生 tool calls，转换成 `ToolCall`。
4. 如果模型返回 JSON action，则规范化为 `AgentAction`。
5. 如果输出不可解析，会追加修复提示再请求一次。
6. 如果仍失败，则根据已有工具观察生成保守 fallback answer 或请求用户补充。

Reasoner 主要负责：

- 根据未知工具错误改用可用工具。
- 根据 validation error 修复参数。
- 根据工具观察继续调用工具。
- 在证据足够时生成最终回答。
- 在无法继续时请求用户输入。

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
7. 如果出现审批请求，当前 step summary 为 waiting for tool approval，并停止继续执行后续 step。

当前 Executor 不做：

- DAG 并发。
- `depends_on` 依赖排序。
- LLM 驱动执行策略。
- 自动重试。
- 细粒度失败分类。

## Reflector

位置：`agents/reflector.py`

当前 Reflector 是简化规则实现，不调用 LLM。

规则：

- 如果所有 plan step 都完成，返回 `done=True, confidence=0.9`。
- 如果存在未完成 step，返回 `done=False, confidence=0.4, next_action="ask_user"`。

后续要做 LLM 驱动的 Reflector，应保持 `Critique` 输出协议不变。

## 工具系统

工具系统位于 `tools/`。

### ToolSchema / ToolPermission / ToolPermissionPolicy

位置：`tools/schemas.py`

`ToolSchema` 描述工具能力：

- `name`
- `description`
- `input_schema`
- `risk`
- `permission`
- `read_only`
- `concurrency_safe`
- `destructive`
- `cache_ttl_s`

`ToolPermission` 描述工具声明的权限需求：

- `filesystem`
- `shell`
- `network`
- `approval_required`

`ToolPermissionPolicy` 描述运行时策略：

- `default_shell`
- `workspace_write`
- `network`
- `destructive_commands`

`ToolSchema.context_definition()` 用于注入 Planner / Reasoner context。

`ToolSchema.llm_tool_definition()` 用于生成 OpenAI-compatible 原生 tool schema。

### BaseTool / ToolContext / Workspace

位置：`tools/base.py`

`Workspace`：

- `resolve()`：解析写路径，必须在 workspace 内。
- `resolve_read()`：解析读路径；相对路径限制在 workspace 内，绝对路径 / `~` 路径允许在 workspace 或 home read roots 下读取。

`BaseTool.validate_input()`：

- 根据 input_schema 的 required 字段做基础必填校验。

`BaseTool.check_permissions()`：

- 根据工具 schema 和运行时 policy 判断 allow / ask / deny。
- 对 shell、network、workspace write、destructive operation 做策略检查。
- 高风险工具默认可能返回 ask，但具体工具可以覆盖此逻辑。

### ToolRegistry

位置：`tools/registry.py`

保存工具实例：

- `register(tool)`
- `get(name)`
- `schemas(read_only=None)`
- `definitions()`
- `llm_tools()`

重复注册同名工具会抛 `ValueError`。

### ToolRouter

位置：`tools/router.py`

根据 `ToolCall.name` 找到工具并执行。

当前能力：

- 工具名别名归一化，例如 `ls`、`list`、`readfile`、`search`、`bash`。
- 参数别名归一化，例如 `file_path`、`filepath`、`dir`、`directory` 转为 `path`。
- 未知工具返回结构化失败结果，附带 available_tools 和 tool_definitions。
- 输入校验失败返回 required_args、optional_args、input_schema。
- `call.requires_approval and not call.approved` 时返回 approval_required。
- 调用工具自身的 `check_permissions()`。
- policy 为 deny 时返回失败。
- policy 为 ask 且 call 未 approved 时返回 approval_required。
- 成功或失败都会写入 audit metadata。
- 工具异常会被捕获并转成失败 `ToolResult`。

当前限制：

- 能产生审批请求，但还没有审批后继续执行。
- 没有持久化审计查询。

### 内置工具

位置：`tools/builtin/`

当前内置六个核心工具：

- `Read`：读取 UTF-8 文本文件。
- `Write`：新建或覆盖 UTF-8 文本文件。
- `Edit`：替换已有 UTF-8 文本文件中的文本。
- `Grep`：用正则搜索 UTF-8 文本文件。
- `Glob`：按路径模式查找文件或目录。
- `Bash`：在 workspace 中执行 shell 命令。

### Bash 当前行为

`BashTool`：

- schema 风险等级为 `high`。
- 会根据 `default_shell` 判断 shell 是否允许。
- 会用正则识别部分 destructive command。
- destructive command 受 `destructive_commands` 策略控制。
- 如果 `default_shell=allow` 且命令不触发 destructive 策略，则直接允许执行。
- 如果 `default_shell=ask` 或 destructive 策略为 `ask`，则返回 approval_required。
- 如果 `default_shell=deny`，则拒绝。

当前 `configs/default.yaml` 中 `default_shell: allow`，所以 Bash 默认启用且普通命令可直接执行。

## LLM Client

位置：`llm/client.py`

当前只有 `OpenAICompatibleClient`，使用标准库 `urllib` 调用 OpenAI-compatible 接口。

支持：

- `list_models()`：请求 `/v1/models`。
- `chat(messages, max_tokens, temperature, tools)`：请求 `/v1/chat/completions`。

返回模型：

- `ChatMessage`
- `ChatResponse`

`ChatMessage.role` 只允许：

- `system`
- `user`
- `assistant`

`ChatResponse` 保存：

- `model`
- `content`
- `tool_calls`
- `raw`

默认配置在 `configs/default.yaml`：

- `base_url: http://localhost:8500`
- `chat: MiniMax-M2.5`
- `planner: MiniMax-M2.5`
- `executor: MiniMax-M2.5`
- `reflector: MiniMax-M2.5`

注意：`reflector` 字段目前尚未被 LLM Reflector 使用。

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
- 可用 tool definitions。
- 可用 skill schemas。
- workspace。
- environment。
- session context。
- 当前用户请求。

`session_context` 会被拼接成：

```text
<session_context>

Current user request:
<request.content>
```

当前还没有注入：

- 长期 memory。
- 文件索引。
- RAG 检索结果。

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
- `LoggingConfig`
- `AppConfig`

`loader.py` 提供：

- `load_config(path="configs/default.yaml")`

配置文件使用 YAML。当前配置重点控制：

- runtime 默认模式和最大迭代次数。
- OpenAI-compatible 模型地址和模型名。
- context 预算。
- shell / write / network / destructive 权限策略。
- memory 开关。
- logging 开关和 JSONL 文件路径。

当前 `configs/default.yaml` 中权限较开放：

```yaml
permissions:
  default_shell: allow
  workspace_write: allow
  network: allow
  destructive_commands: allow
```

## CLI

位置：`api/cli.py`

CLI 使用 Typer 和 Rich。

### run

```bash
agent-system run "任务"
```

创建 ACT 模式 `UserRequest`，调用 `_run_request()`，打印 Runtime 事件。

常用参数：

- `--config`
- `--json`
- `--show-tool-results`
- `--user-id`
- `--workspace-id`

### plan

```bash
agent-system plan "任务"
```

创建 PLAN 模式 `UserRequest`，只生成 plan，不执行工具。

### runtime-chat

```bash
agent-system runtime-chat
```

每轮用户输入都会：

1. 先处理 runtime-chat 斜杠命令。
2. 普通输入会创建带固定 `session_id` 的 `UserRequest`。
3. 调用 `AgentRuntime`。
4. 根据 Runtime events 生成 fallback answer。
5. 如果工具结果全部成功，用 Chat LLM 合成最终回复。
6. 把本地 history 保留在 CLI 中，用于最终回复合成。

支持命令：

- `/help`
- `/clear`
- `/tools`
- `/exit`
- `/quit`

当前不支持：

- `/approve`
- `/deny`
- `/resume`
- `/tasks`

## 测试现状

测试覆盖包括：

- import。
- config loader。
- core models。
- OpenAI-compatible client。
- Planner Agent。
- Runtime factory。
- Runtime event flow。
- Reasoner 继续调用工具和生成最终回答。
- 未知工具错误后 Reasoner 修复。
- validation error 后 Reasoner 修复。
- JSONL logging。
- PLAN 模式等待审批。
- checkpoint 保存。
- session 保存与隔离。
- session context 注入 Planner。
- tool approval event。
- session context 对工具结果摘要进行截断。

本地真实 LLM 测试默认跳过，需要设置环境变量：

```bash
AGENT_SYSTEM_RUN_LOCAL_LLM_TESTS=1 uv run pytest tests/integration
```

## 后续开发优先修改位置

### 工具审批续跑

重点文件：

- `runtime/session.py`
- `runtime/loop.py`
- `api/cli.py`
- `models/tools.py`
- `tests/unit/runtime/test_runtime_loop.py`

目标：

- 保存 pending approvals。
- 增加 `/approve`、`/deny`、`/resume`。
- 审批后继续执行原 ToolCall。

### SQLite Session / Checkpoint

重点文件：

- `runtime/session.py`
- `runtime/checkpoint.py`
- `runtime/factory.py`
- `config/models.py`
- `configs/default.yaml`

目标：

- 抽象 SessionStore / CheckpointStore 协议。
- 新增 SQLite 实现。
- 进程重启后恢复 session / task。

### LLM Reflector

重点文件：

- `agents/reflector.py`
- `prompts/templates/reflector.md`
- `runtime/factory.py`
- `runtime/loop.py`

目标：

- 使用 LLM 判断是否真的完成。
- 保留规则 fallback。
- 输出仍使用 `Critique`。

### Executor 稳定性

重点文件：

- `execution/executor.py`
- `models/planning.py`
- `tests/unit/execution/`

目标：

- `depends_on` 排序。
- blocked step。
- 失败分类。
- retry 上限。

### 可观测与恢复

重点文件：

- `observability/logging.py`
- `runtime/checkpoint.py`
- `api/cli.py`

目标：

- trace_id。
- task 查询。
- replay。
- 工具调用审计查询。

## 当前不要优先做的事情

建议暂缓：

- 多 Agent / Supervisor。
- Web UI。
- 大规模 MCP 集成。
- 向量数据库长期记忆。
- 分布式 Runtime。
- DAG 并发执行。

原因：当前单 Agent 的审批、恢复、持久化和反思还没有完全稳定。过早扩展会放大状态管理复杂度。
