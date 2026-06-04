# AI Agent 开发计划

## 1. 开发目标

当前项目只有架构设计文档，第一阶段目标不是直接实现完整生产系统，而是先做出一个可运行、可测试、可扩展的单 Agent 最小闭环。

核心闭环：

```text
用户请求 -> 组装上下文 -> 生成计划 -> 执行工具 -> 反思验证 -> 输出结果
```

第一版重点：

- 建立标准 Python 工程结构。
- 固化核心数据模型。
- 实现最小 Runtime 主循环。
- 接入基础工具系统。
- 提供 CLI 入口进行本地验证。
- 保持后续接入真实 LLM、Memory、多 Agent、MCP 的扩展空间。

## 2. 开发原则

- 先可运行，再扩展。
- 先单 Agent，再多 Agent。
- 先内存实现，再持久化实现。
- 先规则或 Mock LLM，再接真实 LLM。
- 先最小权限模型，再扩展复杂权限治理。
- 保持模块边界清晰，避免过早引入复杂基础设施。

## 3. Phase 0：项目初始化

### 目标

把当前文档型项目变成标准 Python 工程。

### 交付内容

- `pyproject.toml`
- `README.md`
- `configs/default.yaml`
- `src/agent_system/` 包结构
- `tests/` 测试目录
- 基础依赖管理

建议依赖：

- `pydantic`
- `pytest`
- `typer`
- `rich`
- `pyyaml`

### 建议目录

```text
agent_system/
  pyproject.toml
  README.md
  configs/
    default.yaml
  src/
    agent_system/
      __init__.py
  tests/
```

### 验收标准

- 可以成功安装项目依赖。
- 可以执行测试命令。
- 包可以被正常 import。
- 不引入业务逻辑，只完成工程骨架。

## 4. Phase 1：核心数据模型

### 目标

先固化 Agent Runtime 的数据边界，为后续 Runtime、工具、LLM、事件流提供统一协议。

### 交付内容

- `RunMode`
- `UserRequest`
- `Step`
- `Plan`
- `ToolCall`
- `ToolResult`
- `Critique`
- `AgentState`
- `AgentEvent`

### 建议路径

```text
src/agent_system/models/
  __init__.py
  request.py
  planning.py
  tools.py
  runtime.py
  events.py
```

### 验收标准

- 所有模型有基础单元测试。
- 模型可以正常序列化和反序列化。
- 字段命名与架构文档保持一致。
- 默认值和枚举值清晰稳定。

## 5. Phase 2：Runtime 主循环

### 目标

实现最小可运行主循环，但暂时不接真实 LLM。

### 交付内容

- `AgentRuntime`
- `PlannerAgent` 占位实现
- `Executor`
- `Reflector`
- 内存版 `CheckpointStore`
- 内存版 `EventBus`

### 初始行为

- Planner 基于规则生成一个简单 Plan。
- Executor 顺序执行 Plan Step。
- Reflector 判断任务是否完成。
- Runtime 通过事件流输出运行状态。

### 建议路径

```text
src/agent_system/runtime/
  __init__.py
  loop.py
  state.py
  checkpoint.py

src/agent_system/agents/
  __init__.py
  planner.py
  reflector.py

src/agent_system/execution/
  __init__.py
  executor.py
```

### 验收标准

- 一个用户请求可以跑完整生命周期。
- 能输出以下事件：
  - `run.started`
  - `plan.created`
  - `execution.completed`
  - `reflection.completed`
  - `run.completed`
- Runtime 有单元测试。
- 不依赖真实 LLM 或外部服务。

## 6. Phase 3：工具系统

### 目标

让 Agent 可以通过统一协议调用基础工具。

### 交付内容

- `BaseTool`
- `ToolSchema`
- `ToolRegistry`
- `ToolRouter`
- 内置工具：
  - `Read`
  - `Write`
  - `Edit`
  - `Grep`
  - `Glob`
  - `Bash`

### 建议路径

```text
src/agent_system/tools/
  __init__.py
  base.py
  registry.py
  router.py
  schemas.py
  builtin/
    __init__.py
    file.py
    grep.py
    shell.py
```

### 初始权限策略

| 工具 | 默认策略 |
| --- | --- |
| `Read` | 允许 |
| `Write` | 允许写工作区并记录事件 |
| `Edit` | 允许修改工作区文件并记录事件 |
| `Grep` | 允许 |
| `Glob` | 允许 |
| `Bash` | 默认关闭，需要显式配置开启 |
| 删除文件 | 第一版不支持 |
| 联网操作 | 第一版不支持 |

### 验收标准

- 工具可以注册、查询和调用。
- 工具返回统一 `ToolResult`。
- 文件读取和搜索工具有测试。
- Shell 工具有超时和错误捕获。
- 工具调用失败不会导致 Runtime 崩溃。

## 7. Phase 4：CLI 入口

### 目标

提供最小可交互入口，方便本地验证 Agent Runtime。

### 交付内容

- `agent-system run "任务内容"`
- `agent-system plan "任务内容"`
- 支持指定 workspace。
- 输出事件流。

### 建议路径

```text
src/agent_system/api/
  __init__.py
  cli.py
```

### 验收标准

- 可以通过命令行发起一次 Agent 任务。
- Plan 模式只输出计划，不执行工具。
- Act 模式执行工具并输出最终结果。
- CLI 输出包含关键事件和最终摘要。

## 8. Phase 5：Context 与 Prompt Registry

### 目标

把 Prompt 和上下文拼装从 Runtime 中拆出来，为后续真实 LLM 调用做准备。

### 交付内容

- `PromptRegistry`
- `ContextAssembler`
- 简化版 `TokenBudget`
- Prompt 模板文件：
  - `system.md`
  - `planner.md`
  - `reflector.md`

### 建议路径

```text
src/agent_system/context/
  __init__.py
  assembler.py
  budget.py

src/agent_system/prompts/
  __init__.py
  registry.py
  templates/
    system.md
    planner.md
    reflector.md
```

### 验收标准

- Prompt 不硬编码在 Agent 类里。
- ContextAssembler 能拼装 request、history、workspace 摘要。
- TokenBudget 能限制各类上下文的最大长度。
- 有基础测试覆盖模板加载和上下文拼装。

## 9. Phase 6：接入真实 LLM

### 目标

把规则 Planner 和 Reflector 替换成真实模型调用，同时保持现有接口稳定。

### 交付内容

- `LLMClient` 抽象
- OpenAI Provider
- 结构化输出解析
- Planner 使用 LLM 生成 `Plan`
- Reflector 使用 LLM 生成 `Critique`
- Mock Provider 用于测试

### 建议路径

```text
src/agent_system/llm/
  __init__.py
  client.py
  providers.py
  streaming.py
```

### 验收标准

- 没有 API Key 时测试仍可运行。
- LLM 调用可以被 Mock。
- LLM 输出格式错误时有明确错误处理。
- Planner 和 Reflector 不直接依赖具体模型厂商 SDK。

## 10. Phase 7：可观测与恢复

### 目标

让运行过程可追踪、可审计、可恢复。

### 交付内容

- 结构化日志
- 文件或 SQLite 版 Checkpoint
- `task_id`
- `session_id`
- `trace_id`
- 工具调用记录
- 简单 Replay 支持

### 建议路径

```text
src/agent_system/observability/
  __init__.py
  logging.py

src/agent_system/runtime/
  checkpoint.py
  session.py
```

### 验收标准

- 每次运行有完整事件记录。
- Runtime 异常时能保留最后状态。
- 可以根据 `task_id` 查看历史事件。
- 工具调用输入、输出摘要和错误信息可追踪。

## 11. 暂不纳入第一版的能力

以下能力先不做，避免第一版复杂度过高：

- 多 Agent Supervisor
- 向量记忆
- MCP Server
- Web UI
- Temporal / Redis / Kafka
- 复杂权限策略
- 插件市场
- 分布式 Worker
- 企业级审计和数据治理

这些能力可以在单 Agent Runtime 稳定后逐步引入。

## 12. 推荐实施顺序

```text
Phase 0 -> Phase 1 -> Phase 2 -> Phase 3 -> Phase 4 -> Phase 5 -> Phase 6 -> Phase 7
```

优先级说明：

1. 先完成 `Phase 0 + Phase 1`，建立工程骨架和数据协议。
2. 再完成 `Phase 2`，跑通无 LLM 的 Runtime 主循环。
3. 接着完成 `Phase 3 + Phase 4`，形成可本地使用的 Agent。
4. 最后再接入真实 LLM、上下文系统和可观测能力。

## 13. 第一阶段里程碑

### Milestone 1：可导入工程

包含：

- 项目骨架
- 包结构
- 基础配置
- 测试框架

验收：

```text
pytest
python -c "import agent_system"
```

### Milestone 2：模型协议稳定

包含：

- 请求模型
- 计划模型
- 工具模型
- Runtime 状态模型
- 事件模型

验收：

```text
pytest tests/unit/models
```

### Milestone 3：无 LLM Runtime 闭环

包含：

- Planner
- Executor
- Reflector
- Runtime
- 事件流

验收：

```text
agent-system run "读取当前目录结构"
```

### Milestone 4：基础工具可用

包含：

- 文件读取
- 文件写入
- 文件修改
- 文本搜索
- 路径匹配
- 受控 Shell

验收：

```text
agent-system run "搜索项目里的 AgentRuntime"
```

## 14. 风险与控制

| 风险 | 控制方式 |
| --- | --- |
| 过早实现多 Agent 导致复杂度失控 | 第一版只做单 Agent |
| 真实 LLM 输出不稳定 | 先用规则和 Mock Provider 固化接口 |
| 工具副作用不可控 | Shell 默认关闭，删除和联网第一版不支持 |
| 上下文系统过早复杂化 | 先做简化 ContextAssembler |
| 测试成本后置 | 每个 Phase 都要求基础单元测试 |

## 15. 后续扩展方向

单 Agent Runtime 稳定后，可以继续扩展：

- Plan Mode 审批流
- Memory Manager
- MCP Client / Server
- 多 Agent Supervisor
- DAG Scheduler
- WebSocket 事件流
- OpenTelemetry
- Eval Harness
- 插件系统
