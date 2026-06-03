# 项目说明与进展

## 项目概览

本项目目标是实现一个面向生产级场景的 Python AI Agent Runtime。

当前设计参考 Claude Code、Codex、Cursor Agent 等现代 Agent 产品的公开设计思想，核心形态是：

```text
用户请求 -> 上下文组装 -> Planner 生成计划 -> Executor 执行工具 -> Reflector 校验结果 -> 输出响应
```

项目当前仍处于早期工程化阶段，已完成基础 Python 工程骨架、核心数据模型、最小 Runtime 主循环、本地 MiniMax 2.5 Planner / Chat LLM 接入、ChatGPT 式 CLI、Runtime 对话入口、工具系统到 Runtime Executor 的接入、结构化 ToolCall 执行、Prompt Registry / Planner Context 组装，以及 Skills 模块。当前还没有实现多 Agent 能力或 LLM 驱动的 Reflector / Executor。

## 重要文档

| 文件 | 说明 |
| --- | --- |
| `docs/README.md` | 文档索引和推荐阅读顺序 |
| `docs/codebase-guide.md` | 当前代码结构、运行链路、模块职责和扩展点 |
| `docs/architecture.md` | 完整架构设计方案，包含模块划分、数据模型示例、Runtime 流程、工具系统、Memory、Context、权限、可观测等设计 |
| `docs/development-plan.md` | 分阶段开发计划，从项目初始化到 Runtime、工具系统、CLI、Context、LLM、可观测 |
| `docs/next-development.md` | 下一步开发建议：Runtime 多轮任务状态 |
| `docs/project-status.md` | 当前项目状态和交接说明，供后续 Agent 快速接手 |
| `README.md` | 项目简介、安装方式、测试命令 |

## 当前目录结构

```text
.
├── docs/
│   ├── README.md
│   ├── architecture.md
│   ├── development-plan.md
│   ├── next-development.md
│   └── project-status.md
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

## 已完成进展

### Phase 0：项目初始化

状态：已完成。

已交付：

- `pyproject.toml`
- `README.md`
- `configs/default.yaml`
- `src/agent_system/__init__.py`
- `tests/test_import.py`
- `.gitignore`

影响范围：

- 项目已经具备标准 Python 包结构。
- 可以使用 `uv run pytest` 执行测试。
- 当前测试只验证包可以正常导入。

验证结果：

```text
uv run pytest
50 passed, 2 skipped
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

已实现模型：

- `RunMode`
- `UserRequest`
- `Step`
- `Plan`
- `ToolCall`
- `ToolResult`
- `Critique`
- `AgentState`
- `AgentEvent`

影响范围：

- 项目已经具备 Runtime、工具系统和 LLM 接入所需的基础协议模型。
- 模型字段参考 `docs/architecture.md` 中的核心数据模型示例。
- 当前只实现数据模型和测试，没有实现 Runtime 执行逻辑。

验证结果：

```text
uv run pytest
50 passed, 2 skipped
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
- 执行结果模型 `StepResult` 和 `ExecutionResult`

影响范围：

- 一个 `UserRequest` 已经可以跑完整 ACT 模式生命周期。
- PLAN 模式会在生成计划后输出 `run.waiting_for_approval` 并停止。
- Runtime 当前只使用 mock step 执行结果，不调用真实工具或真实 LLM。

验证结果：

```text
uv run pytest
50 passed, 2 skipped
```

### ChatGPT 式 CLI

状态：已完成。

已交付：

- `src/agent_system/api/cli.py`
- `src/agent_system/api/__init__.py`
- `tests/unit/api/test_cli.py`
- `pyproject.toml` 中的 `agent-system` 命令入口

已支持命令：

- `agent-system run "任务内容"`
- `agent-system plan "任务内容"`
- `agent-system chat`
- `agent-system runtime-chat`

常用参数：

- `--config configs/default.yaml`
- `--no-llm`
- `--json`
- `--user-id`
- `--workspace-id`

影响范围：

- 可以从命令行调用当前 Runtime。
- 默认使用 `configs/default.yaml` 中配置的 MiniMax Planner。
- `agent-system chat` 会直接调用 `model.chat`，保留当前会话上下文历史，并只输出 Assistant 回复。
- `agent-system chat` 默认隐藏 `<think>...</think>` 内容，可用 `--show-reasoning` 显示。
- `agent-system runtime-chat` 每轮都会经过 `AgentRuntime`，再把事件和工具结果整理成 Assistant 回复。
- `--no-llm` 可切换到规则 Planner，方便无本地模型时测试。
- 当前 Executor 已能执行明确建议的内置工具；没有工具建议的步骤仍会走 mock 执行。

验证结果：

```text
uv run pytest
50 passed, 2 skipped

uv run agent-system plan "为项目生成一个下一步开发计划" --json
成功通过 MiniMax 生成 plan.created 事件
```

### 本地 MiniMax 2.5 接入

状态：已接入默认配置和 Runtime 工厂。

本地服务：

```text
http://localhost:8500
```

已探测接口：

- `GET /v1/models`
- `POST /v1/chat/completions`

已确认模型：

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

影响范围：

- 新增一个最小 OpenAI-compatible LLM client。
- `configs/default.yaml` 默认指向 `http://localhost:8500` 和 `MiniMax-M2.5`。
- `create_runtime_from_config()` 会按配置创建带 LLM client 的 `PlannerAgent`。
- `PlannerAgent` 会优先使用 LLM 生成 `Plan`，LLM 输出不可解析时回退到规则计划。
- 默认 `uv run pytest` 会跳过真实本地服务测试，避免未启动本地模型时失败。

验证结果：

```text
uv run pytest
50 passed, 2 skipped

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

影响范围：

- 工具可以注册、查询和调用。
- 工具统一返回 `ToolResult`。
- 文件工具限制在 workspace 内，阻止路径越界。
- `grep.search` 支持正则搜索文本文件。
- `shell.run` 默认禁用，显式启用后支持超时、stdout、stderr 和 returncode。
- 当前工具系统已接入 `Executor` 的保守路径；只有 Step 明确列出内置工具名时才会调用工具。

验证结果：

```text
uv run pytest
50 passed, 2 skipped
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

影响范围：

- Planner 可以产出结构化 `ToolCall`，减少从自然语言 objective 猜参数。
- Executor 优先执行 `step.tool_calls`，没有结构化调用时才回退到 `suggested_tools + objective` 推断。
- JSON 事件中保留完整 `tool_results`，方便脚本消费。
- 普通 CLI 输出默认隐藏完整工具结果，`--show-tool-results` 显示摘要。

验证结果：

```text
uv run pytest
50 passed, 2 skipped
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

影响范围：

- Planner system prompt 已从 Python 代码迁移到模板文件。
- `ContextAssembler` 会拼装 system prompt、planner prompt、用户请求。
- Planner context 会注入 workspace 信息和工具 schema。
- Runtime 工厂会把已注册工具 schema 传给 Planner context。

验证结果：

```text
uv run pytest
50 passed, 2 skipped
```

### Skills 模块

状态：已完成。

已交付：

- `src/agent_system/skills/schemas.py`
- `src/agent_system/skills/base.py`
- `src/agent_system/skills/registry.py`
- `src/agent_system/skills/__init__.py`
- `src/agent_system/skills/builtin/__init__.py`
- `tests/unit/skills/test_skill_registry.py`

已实现：

- `SkillSchema`
- `BaseSkill`
- `SkillRegistry`
- 默认内置 skills：`coding`、`runtime`、`review`
- Planner Context 中的 skills schema 注入

影响范围：

- Skills 当前是能力元数据层，不直接执行动作。
- Runtime 工厂会注册默认 skills，并把 skills schema 交给 `ContextAssembler`。
- Planner prompt 可以看到可用 skills、触发词、建议工具和 prompt hints。
- 现有 Runtime、Executor 和 ToolRouter 行为不变。

验证结果：

```text
uv run pytest
50 passed, 2 skipped
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

影响范围：

- Runtime 模式现在可以像对话一样使用。
- `runtime-chat --no-llm` 会直接展示 Runtime 工具执行结果。
- 默认 `runtime-chat` 会先跑 Runtime，再用 `model.chat` 合成自然语言回复。
- `--show-events` 可用于调试完整 Runtime 事件流。

验证结果：

```text
uv run pytest
50 passed, 2 skipped
```

## 当前技术选择

当前 `pyproject.toml` 已声明：

- Python：`>=3.11`
- 包构建：`hatchling`
- 运行依赖：
  - `pydantic`
  - `pyyaml`
  - `rich`
  - `typer`
- 开发依赖：
  - `pytest`

说明：

- 当前已经实现最小 Runtime 主循环，并已通过配置把 LLM client 接入 `PlannerAgent` 和 Runtime 工厂；工具系统已接入 Runtime `Executor` 的保守执行路径。
- `pydantic` 已用于 Phase 1 核心数据模型。
- `typer` 和 `rich` 预留给后续 CLI。
- `pyyaml` 预留给配置加载。

## 当前配置

默认配置文件：

```text
configs/default.yaml
```

当前包含：

- Runtime 默认迭代次数和运行模式。
- 本地 MiniMax 2.5 OpenAI-compatible 模型配置。
- Context token budget 配置。
- 初始权限策略。
- Memory 默认关闭。

注意：

- Shell 默认策略是 `deny`。
- 网络默认策略是 `deny`。
- Memory 当前未启用。

## 下一步任务

下一步建议继续完善权限策略和工具调用审批。

如果优先关注 Agent 主体能力，见 `docs/next-development.md`，建议先做 Runtime 多轮任务状态。

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

这些内容应等单 Agent Runtime 稳定后再逐步引入。

## 开发约束

后续开发应遵守以下原则：

- 严格按需求做最小改动。
- 不做无关重构。
- 新增能力优先参考 `docs/development-plan.md` 的阶段顺序。
- 数据结构优先参考 `docs/architecture.md`。
- 每个阶段都补充对应测试。
- 修改后运行 `uv run pytest` 验证。

## 常用命令

安装开发依赖：

```bash
pip install -e ".[dev]"
```

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

检查项目文件：

```bash
rg --files
```

## 给后续 Agent 的接手提示

接手本项目时建议按以下顺序阅读：

1. 先读 `docs/project-status.md`，了解当前状态。
2. 再读 `docs/development-plan.md`，确认下一阶段任务。
3. 需要架构细节时读 `docs/architecture.md`。
4. 开始编码前用 `rg --files` 查看实际文件状态。
5. 完成修改后运行 `uv run pytest`。

