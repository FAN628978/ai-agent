# AI Agent

这是一个面向生产级 AI Agent Runtime 的 Python 工程骨架。

当前阶段目标是先建立可安装、可测试、可扩展的最小工程结构，后续再逐步实现 Runtime 工具执行、上下文管理、LLM 驱动规划和可观测能力。

## 项目文档

- `docs/README.md`：文档索引和推荐阅读顺序。
- `docs/architecture.md`：完整架构设计方案。
- `docs/development-plan.md`：分阶段开发计划。
- `docs/project-status.md`：当前项目状态和交接说明。
- `docs/next-development.md`：下一步开发建议和后续大模块清单。

## 当前阶段

当前已完成 `Phase 0：项目初始化`、`Phase 1：核心数据模型`、`Phase 2：Runtime 主循环`、`Phase 3：工具系统`，并已将本地 MiniMax 2.5 作为 OpenAI-compatible Planner 和 Chat LLM 写入默认配置。

已包含：

- Python 包结构。
- 基础配置文件。
- 测试目录。
- 项目元数据和依赖声明。
- 核心数据模型。
- 最小 Runtime 主循环。
- 配置驱动的本地 MiniMax Planner LLM 接入。
- ChatGPT 式 CLI 连续对话入口。
- Runtime 对话入口。
- 结构化 ToolCall 规划、执行和工具结果展示。
- Prompt Registry 与 Planner Context 组装。
- Skills 模块、默认 skills 注册与 Planner Context 注入。

## 开发环境

建议使用 Python 3.11 或更高版本。

安装开发依赖：

```bash
pip install -e ".[dev]"
```

运行测试：

```bash
pytest
```

## CLI 使用

查看命令：

```bash
uv run agent-system --help
```

生成计划，默认使用 `configs/default.yaml` 中的 MiniMax：

```bash
uv run agent-system plan "为项目生成一个下一步开发计划"
```

执行一次请求：

```bash
uv run agent-system run "帮我分析当前项目"
```

进入 ChatGPT 式连续对话：

```bash
uv run agent-system chat
```

聊天模式会保留当前会话上下文历史，默认使用 `configs/default.yaml` 中的 `model.chat`，并默认隐藏 `<think>...</think>` 内容。需要显示推理块时可加：

```bash
uv run agent-system chat --show-reasoning
```

进入 Runtime 对话模式：

```bash
uv run agent-system runtime-chat
```

Runtime 对话模式每轮都会先经过 `AgentRuntime`，再把执行结果整理成 Assistant 回复。无模型调试可用：

```bash
uv run agent-system runtime-chat --no-llm
```

使用规则 Planner，不调用本地模型：

```bash
uv run agent-system plan "Inspect project" --no-llm
```

输出 JSON Lines：

```bash
uv run agent-system plan "Inspect project" --json
```

显示工具结果摘要：

```bash
uv run agent-system run "Read README.md" --no-llm --show-tool-results
```

注意：当前 CLI 已能对话、生成计划，并能通过 Runtime 执行明确建议的低风险工具。没有工具建议的步骤仍会走 mock 执行。

## 本地 MiniMax 测试

项目已包含一个最小 OpenAI-compatible LLM client，并可通过 `configs/default.yaml` 创建使用本地 MiniMax 的 Runtime。

默认配置：

```yaml
model:
  provider: openai-compatible
  base_url: http://localhost:8500
  chat: MiniMax-M2.5
  planner: MiniMax-M2.5
  executor: MiniMax-M2.5
  reflector: MiniMax-M2.5
  timeout_s: 30
  max_tokens: 1024
  temperature: 0.2
  chat_history_limit: 20
```

默认地址：

```text
http://localhost:8500
```

默认模型：

```text
MiniMax-M2.5
```

运行本地集成测试：

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

## 后续计划

下一步建议继续完善权限策略和工具调用审批，尤其是 `shell.run` 的显式启用和审计。
