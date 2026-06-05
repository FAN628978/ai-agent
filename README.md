# AI Agent

这是一个面向生产级 AI Agent Runtime 的 Python 工程。当前已经从“最小工程骨架”推进到“可运行的单 Agent Runtime 原型”阶段。

项目核心目标是实现一个可安装、可测试、可扩展的本地 Agent Runtime，并逐步完善工具执行、上下文管理、LLM 规划、观察后推理、权限审批、会话状态、日志审计和恢复能力。

## 项目文档

- `docs/README.md`：文档索引和推荐阅读顺序。
- `docs/codebase-guide.md`：当前代码结构、运行链路和扩展点说明。
- `docs/architecture.md`：完整架构设计方案。
- `docs/development-plan.md`：分阶段开发计划。
- `docs/project-status.md`：当前项目状态和交接说明。
- `docs/next-development.md`：下一步开发建议：审批续跑、持久化 Session 与 LLM Reflector。

## 当前阶段

当前已完成：

- `Phase 0：项目初始化`
- `Phase 1：核心数据模型`
- `Phase 2：Runtime 主循环`
- `Phase 3：工具系统`
- OpenAI-compatible MiniMax 本地模型接入
- Runtime 工厂组装
- Prompt Registry 与 Planner Context 组装
- Skills 元数据注册与注入
- 结构化 `ToolCall` 规划和执行
- `AgentReasoner` 观察工具结果后继续决策
- `SessionRecord` / `InMemorySessionStore` 多轮状态基础能力
- `JsonlEventLogger` 结构化事件日志

当前主体链路：

```text
CLI -> UserRequest -> create_runtime_from_config()
    -> AgentRuntime.run()
    -> SessionRecord.context_summary()
    -> PlannerAgent.make_plan()
    -> Executor.execute()
    -> ToolRouter.invoke()
    -> AgentReasoner.next_action() / Reflector.evaluate()
    -> AgentEvent stream
    -> SessionRecord.record_run()
```

## 已包含能力

- 标准 Python 包结构。
- `pyproject.toml` 项目元数据和 CLI 入口。
- YAML 配置加载。
- 核心数据模型：`UserRequest`、`Plan`、`Step`、`ToolCall`、`ToolResult`、`Critique`、`AgentState`、`AgentEvent`。
- Runtime 主循环：`AgentRuntime`。
- 内存 checkpoint：`InMemoryCheckpointStore`。
- 内存 session：`SessionRecord`、`InMemorySessionStore`。
- LLM Planner：支持 JSON plan 和原生 tool calls。
- Planner 失败后的保守规则兜底。
- Reasoner：根据 plan、session context、tool observations 决定继续调用工具、最终回答或请求用户补充。
- Executor：顺序执行 `Plan.steps`，优先执行结构化 `step.tool_calls`。
- ToolRouter：工具名归一化、输入校验、权限策略、审批请求、审计 metadata、异常捕获。
- 内置工具：`Read`、`Write`、`Edit`、`Grep`、`Glob`、`Bash`。
- CLI：`run`、`plan`、`runtime-chat`。
- `runtime-chat` 斜杠命令：`/help`、`/clear`、`/tools`、`/exit`、`/quit`。
- JSON Lines 事件输出。
- 工具结果摘要展示。
- OpenAI-compatible LLM client。
- 本地 MiniMax 配置。
- 单元测试和本地集成测试入口。

## 开发环境

建议使用 Python 3.11 或更高版本。

安装开发依赖：

```bash
pip install -e ".[dev]"
```

或使用 `uv`：

```bash
uv sync --dev
```

运行测试：

```bash
pytest
```

或：

```bash
uv run pytest
```

## CLI 使用

查看命令：

```bash
uv run agent-system --help
```

生成计划：

```bash
uv run agent-system plan "为项目生成一个下一步开发计划"
```

执行一次请求：

```bash
uv run agent-system run "帮我分析当前项目"
```

显示工具结果摘要：

```bash
uv run agent-system run "Read README.md" --show-tool-results
```

输出 JSON Lines：

```bash
uv run agent-system plan "Inspect project" --json
```

进入 Runtime 对话模式：

```bash
uv run agent-system runtime-chat
```

Runtime 对话模式每轮都会先经过 `AgentRuntime`，再把执行结果整理成 Assistant 回复。它使用固定 `session_id` 调用 Runtime，Runtime 内部会读取并写回 `SessionRecord`；CLI 仍保留一份本地 history，用于最终回复合成。

## 默认 MiniMax 配置

项目已包含一个最小 OpenAI-compatible LLM client，并可通过 `configs/default.yaml` 创建使用本地 MiniMax 的 Runtime。

当前默认配置重点如下：

```yaml
model:
  provider: openai-compatible
  base_url: http://localhost:8500
  chat: MiniMax-M2.5
  planner: MiniMax-M2.5
  executor: MiniMax-M2.5
  reflector: MiniMax-M2.5
  timeout_s: 30
  max_tokens: 100000
  temperature: 0.7
  chat_history_limit: 20

permissions:
  default_shell: allow
  workspace_write: allow
  network: allow
  destructive_commands: allow

logging:
  enabled: true
  path: logs/agent-system.jsonl
  level: info
```

注意：当前 `configs/default.yaml` 为本地开发便利，默认允许 shell、workspace write、network 和 destructive commands。后续如果用于更真实的生产场景，建议把高风险权限改为 `ask` 或 `deny`，并优先完善审批续跑能力。

## 本地集成测试

运行本地 LLM 集成测试：

```bash
AGENT_SYSTEM_RUN_LOCAL_LLM_TESTS=1 uv run pytest tests/integration
```

Windows PowerShell：

```powershell
$env:AGENT_SYSTEM_RUN_LOCAL_LLM_TESTS='1'
$env:AGENT_SYSTEM_LLM_BASE_URL='http://localhost:8500'
$env:AGENT_SYSTEM_LLM_MODEL='MiniMax-M2.5'
uv run pytest tests\integration
```

## 当前主要不足

- 审批后继续执行尚未形成完整闭环：已有 `run.waiting_for_tool_approval`，但还缺少 `/approve`、`/deny`、`resume`。
- Session 仍是内存版，进程退出后状态丢失。
- Checkpoint 仍是内存版，不支持持久化恢复。
- Reflector 仍是规则实现，还没有 LLM Reflector。
- Executor 还没有真正处理 `depends_on` 依赖排序、失败分类和自动重试。
- 日志已有 JSONL，但还缺少 trace 查询、replay 和工具调用级审计查询。
- MCP、多 Agent、Web UI 仍属于后续扩展。

## 后续计划

下一步建议优先完善：

1. 工具审批后的继续执行。
2. SQLite SessionStore / CheckpointStore。
3. LLM Reflector。
4. Executor 失败分类、依赖排序和重试策略。
5. 可观测、查询和恢复能力。

更详细的开发路线见 `docs/next-development.md`。
