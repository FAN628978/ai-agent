from __future__ import annotations

import asyncio
import json
from pathlib import Path
from uuid import uuid4

import typer
from rich.console import Console

from agent_system.config import load_config
from agent_system.llm import ChatMessage, OpenAICompatibleClient
from agent_system.models import AgentEvent, RunMode, UserRequest
from agent_system.runtime import AgentRuntime, create_runtime_from_config
from agent_system.tools.schemas import ToolSchema

app = typer.Typer(help="Run the local AI Agent runtime.")
console = Console()


def main() -> None:
    app()


@app.command()
def run(
    content: str = typer.Argument(..., help="User request to send to the agent."),
    config: Path = typer.Option(Path("configs/default.yaml"), "--config", "-c", help="Config file path."),
    user_id: str = typer.Option("local-user", help="User id for the request."),
    workspace_id: str = typer.Option(".", help="Workspace id or path for the request."),
    json_output: bool = typer.Option(False, "--json", help="Print events as JSON Lines."),
    no_llm: bool = typer.Option(False, "--no-llm", help="Use the rule-based planner instead of configured LLM."),
    show_tool_results: bool = typer.Option(False, "--show-tool-results", help="Print tool result summaries."),
) -> None:
    """Run a request in ACT mode."""
    request = _make_request(content, RunMode.ACT, user_id, workspace_id)
    events = asyncio.run(_run_request(request, config, no_llm))
    _print_events(events, json_output, show_tool_results=show_tool_results)


@app.command()
def plan(
    content: str = typer.Argument(..., help="User request to plan."),
    config: Path = typer.Option(Path("configs/default.yaml"), "--config", "-c", help="Config file path."),
    user_id: str = typer.Option("local-user", help="User id for the request."),
    workspace_id: str = typer.Option(".", help="Workspace id or path for the request."),
    json_output: bool = typer.Option(False, "--json", help="Print events as JSON Lines."),
    no_llm: bool = typer.Option(False, "--no-llm", help="Use the rule-based planner instead of configured LLM."),
) -> None:
    """Create a plan and stop before execution."""
    request = _make_request(content, RunMode.PLAN, user_id, workspace_id)
    events = asyncio.run(_run_request(request, config, no_llm))
    _print_events(events, json_output, show_tool_results=False)


@app.command("runtime-chat")
def runtime_chat(
    config: Path = typer.Option(Path("configs/default.yaml"), "--config", "-c", help="Config file path."),
    user_id: str = typer.Option("local-user", help="User id for the request."),
    workspace_id: str = typer.Option(".", help="Workspace id or path for the request."),
    no_llm: bool = typer.Option(False, "--no-llm", help="Use rule-based runtime responses."),
    show_events: bool = typer.Option(False, "--show-events", help="Print runtime events before the answer."),
    show_reasoning: bool = typer.Option(False, "--show-reasoning", help="Show <think>...</think> reasoning blocks."),
) -> None:
    """Start a chat loop that routes each turn through AgentRuntime."""
    app_config = load_config(config)
    session_id = str(uuid4())
    responder = None
    if not no_llm:
        responder = OpenAICompatibleClient(
            base_url=app_config.model.base_url,
            model=app_config.model.chat,
            api_key=app_config.model.api_key,
            timeout_s=app_config.model.timeout_s,
        )
    runtime_config = app_config.model_copy(deep=True)
    if no_llm:
        runtime_config.model.provider = "rule"
    runtime = create_runtime_from_config(runtime_config, workspace_root=workspace_id)
    history: list[tuple[str, str]] = []

    console.print("Runtime chat started. Type '/help' for commands.")
    while True:
        content = typer.prompt("You")
        if _is_exit_command(content):
            raise typer.Exit()
        if _handle_runtime_slash_command(content, history, runtime):
            continue
        if _is_tool_list_request(content):
            answer = _render_available_tools(runtime)
            history.append((content, answer))
            history[:] = history[-app_config.model.chat_history_limit :]
            console.print("[bold green]Assistant[/bold green]")
            console.print(answer)
            continue

        request = UserRequest(
            session_id=session_id,
            user_id=user_id,
            workspace_id=workspace_id,
            content=content,
            mode=RunMode.ACT,
        )
        events = asyncio.run(_run_runtime(runtime, request))
        if show_events:
            _print_events(events, json_output=False, show_tool_results=True)

        answer = _render_runtime_answer(events)
        if responder is not None:
            answer = asyncio.run(
                _synthesize_runtime_answer(
                    client=responder,
                    history=history,
                    user_content=content,
                    events=events,
                    fallback=answer,
                    max_tokens=app_config.model.max_tokens,
                    temperature=app_config.model.temperature,
                    show_reasoning=show_reasoning,
                )
            )
        history.append((content, answer))
        history[:] = history[-app_config.model.chat_history_limit :]
        console.print("[bold green]Assistant[/bold green]")
        console.print(answer)


def _make_request(content: str, mode: RunMode, user_id: str, workspace_id: str) -> UserRequest:
    return UserRequest(
        session_id=str(uuid4()),
        user_id=user_id,
        workspace_id=workspace_id,
        content=content,
        mode=mode,
    )


async def _run_request(request: UserRequest, config_path: Path, no_llm: bool) -> list[AgentEvent]:
    config = load_config(config_path)
    if no_llm:
        config.model.provider = "rule"
    runtime = create_runtime_from_config(config, workspace_root=request.workspace_id)
    return await _run_runtime(runtime, request)


async def _run_runtime(runtime: AgentRuntime, request: UserRequest) -> list[AgentEvent]:
    return [event async for event in runtime.run(request)]


async def _synthesize_runtime_answer(
    client: OpenAICompatibleClient,
    history: list[tuple[str, str]],
    user_content: str,
    events: list[AgentEvent],
    fallback: str,
    max_tokens: int,
    temperature: float,
    show_reasoning: bool,
) -> str:
    messages = [
        ChatMessage(
            role="system",
            content=(
                "You are the final responder for a local AgentRuntime. "
                "Answer the user's latest message directly in concise Chinese. "
                "Use only the runtime observation as ground truth. "
                "Never invent command output or filesystem contents. "
                "If the runtime observation has no real tool result, say that no real tool result is available. "
                "Do not mention internal event names unless useful."
            ),
        )
    ]
    for user, assistant in history[-6:]:
        messages.append(ChatMessage(role="user", content=user))
        messages.append(ChatMessage(role="assistant", content=assistant))
    messages.append(
        ChatMessage(
            role="user",
            content=(
                f"Latest user message:\n{user_content}\n\n"
                f"Runtime observation:\n{_runtime_observation(events)}\n\n"
                f"Fallback answer:\n{fallback}"
            ),
        )
    )
    try:
        response = await client.chat(messages, max_tokens=max_tokens, temperature=temperature)
    except Exception:
        return fallback
    answer = response.content.strip()
    if not show_reasoning:
        answer = _strip_reasoning_blocks(answer).strip()
    return answer or fallback


def _runtime_observation(events: list[AgentEvent], max_chars: int = 8000) -> str:
    payload = json.dumps([event.model_dump(mode="json") for event in events], ensure_ascii=False)
    if len(payload) <= max_chars:
        return payload
    return payload[:max_chars] + "...[truncated]"


def _render_runtime_answer(events: list[AgentEvent]) -> str:
    tool_results = _collect_tool_results(events)
    if tool_results:
        return _render_tool_results_answer(tool_results)

    plan = _event_data(events, "plan.created")
    goal = plan.get("goal") if isinstance(plan, dict) else None
    if _event_data(events, "run.completed"):
        return f"已完成：{goal or '请求已处理'}"

    needs_input = _event_data(events, "run.needs_user_input")
    if needs_input:
        return f"需要补充信息：{needs_input.get('issues', [])}"

    stopped = _event_data(events, "run.stopped")
    if stopped:
        return f"运行已停止：{stopped.get('reason', 'unknown')}"

    return "Runtime 已处理请求，但没有生成可展示的结果。"


def _event_data(events: list[AgentEvent], event_type: str) -> dict[str, object]:
    for event in events:
        if event.type == event_type:
            return event.data
    return {}


def _collect_tool_results(events: list[AgentEvent]) -> list[dict[str, object]]:
    tool_results: list[dict[str, object]] = []
    for event in events:
        if event.type != "execution.completed":
            continue
        raw_results = event.data.get("tool_results", [])
        if isinstance(raw_results, list):
            tool_results.extend(result for result in raw_results if isinstance(result, dict))
    return tool_results


def _render_tool_results_answer(tool_results: list[dict[str, object]]) -> str:
    lines: list[str] = []
    for result in tool_results:
        name = result.get("name")
        ok = result.get("ok")
        content = result.get("content")
        if not ok:
            lines.append(f"{name} 执行失败：{result.get('error')}")
            continue
        if name == "Read" and isinstance(content, dict):
            text = str(content.get("content", ""))
            path = content.get("path", "")
            lines.append(f"{path}\n{text[:4000]}")
        elif name == "Glob" and isinstance(content, dict):
            matches = content.get("matches", [])
            lines.append(f"{content.get('path')} 下匹配 {content.get('pattern')} 的条目数：{content.get('count', 0)}")
            if isinstance(matches, list):
                for entry in matches[:100]:
                    if isinstance(entry, dict):
                        marker = "/" if entry.get("type") == "directory" else ""
                        lines.append(f"- {entry.get('relative_path') or entry.get('name')}{marker}")
        elif name == "Grep" and isinstance(content, dict):
            matches = content.get("matches", [])
            lines.append(f"找到 {content.get('count', 0)} 条匹配：")
            if isinstance(matches, list):
                for match in matches[:20]:
                    if isinstance(match, dict):
                        lines.append(f"{match.get('path')}:{match.get('line_number')}: {match.get('line')}")
        elif name == "Write" and isinstance(content, dict):
            lines.append(f"已写入 {content.get('path')}，字节数：{content.get('bytes_written')}")
        elif name == "Edit" and isinstance(content, dict):
            lines.append(f"已修改 {content.get('path')}，替换次数：{content.get('replacements')}")
        else:
            lines.append(json.dumps(result, ensure_ascii=False))
    return "\n".join(lines)


def _is_exit_command(content: str) -> bool:
    return content.strip().lower() in {"exit", "quit", "/exit", "/quit"}


def _handle_runtime_slash_command(content: str, history: list[tuple[str, str]], runtime: AgentRuntime) -> bool:
    stripped = content.strip()
    if not stripped.startswith("/"):
        return False

    command = stripped.split(maxsplit=1)[0].lower()
    if command == "/help":
        _print_runtime_slash_help()
        return True
    if command == "/clear":
        history.clear()
        console.print("Runtime chat history cleared.")
        return True
    if command == "/tools":
        console.print(_render_available_tools(runtime))
        return True
    if command in {"/exit", "/quit"}:
        raise typer.Exit()

    console.print(f"Unknown command: {command}")
    console.print("Type /help to see available commands.")
    return True


def _print_runtime_slash_help() -> None:
    console.print("Available runtime-chat commands:")
    console.print("/help  Show available commands.")
    console.print("/clear Clear local runtime-chat response history.")
    console.print("/tools Show available Runtime tools.")
    console.print("/exit  Exit runtime-chat.")
    console.print("/quit  Exit runtime-chat.")


def _is_tool_list_request(content: str) -> bool:
    normalized = content.strip().lower()
    if not normalized:
        return False
    tool_keywords = [
        "你有什么工具",
        "你有哪些工具",
        "有什么工具",
        "有哪些工具",
        "可用工具",
        "工具列表",
        "支持什么工具",
        "能用什么工具",
        "what tools",
        "available tools",
        "list tools",
    ]
    return any(keyword in normalized for keyword in tool_keywords)


def _render_available_tools(runtime: AgentRuntime) -> str:
    tools = _runtime_tool_schemas(runtime)
    if not tools:
        return "当前 Runtime 没有暴露可用工具信息。"

    lines = ["当前 Runtime 可用工具："]
    for tool in tools:
        mode = "只读" if tool.read_only else "可写"
        approval = "，需要审批" if tool.permission.approval_required else ""
        lines.append(f"- {tool.name} [{mode}, risk={tool.risk}{approval}]：{tool.description}")
    return "\n".join(lines)


def _runtime_tool_schemas(runtime: AgentRuntime) -> list[ToolSchema]:
    planner = getattr(runtime, "planner", None)
    context = getattr(planner, "context", None)
    tools = getattr(context, "tools", [])
    return [tool for tool in tools if isinstance(tool, ToolSchema)]


def _strip_reasoning_blocks(content: str) -> str:
    result = content
    while True:
        start = result.find("<think>")
        end = result.find("</think>", start + len("<think>"))
        if start < 0 or end < 0:
            return result
        result = result[:start] + result[end + len("</think>") :]


def _print_events(events: list[AgentEvent], json_output: bool, show_tool_results: bool = False) -> None:
    if json_output:
        for event in events:
            print(json.dumps(event.model_dump(mode="json"), ensure_ascii=False))
        return

    for event in events:
        console.print(f"[bold]{event.type}[/bold]")
        data = dict(event.data)
        if event.type == "execution.completed":
            data.pop("tool_results", None)
        if data:
            console.print_json(json.dumps(data, ensure_ascii=False))

    if show_tool_results:
        _print_tool_results(events)


def _print_tool_results(events: list[AgentEvent]) -> None:
    tool_results = _collect_tool_results(events)

    if not tool_results:
        return

    console.print("[bold]tool.results[/bold]")
    for result in tool_results:
        status = "ok" if result.get("ok") else "failed"
        console.print(f"- {result.get('name')} [{status}] {result.get('error') or ''}".rstrip(), markup=False)
