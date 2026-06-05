import asyncio

from agent_system.agents import Reflector
from agent_system.models import ExecutionResult, Plan, RunMode, Step, StepResult


def make_plan() -> Plan:
    return Plan(
        goal="Inspect workspace",
        mode=RunMode.ACT,
        steps=[
            Step(id="step-1", title="Read", objective="Read README.md"),
            Step(id="step-2", title="Summarize", objective="Summarize results", depends_on=["step-1"]),
        ],
    )


def test_reflector_reports_blocked_step_as_not_done() -> None:
    result = ExecutionResult(
        step_results=[
            StepResult(
                step_id="step-1",
                ok=False,
                status="blocked",
                error_type="dependency_failed",
                summary="Step is blocked by failed dependencies: setup",
            )
        ]
    )

    critique = asyncio.run(Reflector().evaluate(goal="Inspect workspace", plan=make_plan(), result=result))

    assert critique.done is False
    assert critique.next_action == "replan"
    assert "blocked steps" in critique.reason
    assert "status=blocked" in critique.missing_items[1]
    assert "error_type=dependency_failed" in critique.issues[1]


def test_reflector_suggests_tool_or_argument_correction_for_tool_errors() -> None:
    result = ExecutionResult(
        step_results=[
            StepResult(
                step_id="step-1",
                ok=False,
                status="failed",
                error_type="unknown_tool",
                summary="Step failed with tool errors: read",
            ),
            StepResult(
                step_id="step-2",
                ok=False,
                status="failed",
                error_type="validation_failed",
                summary="Step failed with tool errors: Read",
            ),
        ]
    )

    critique = asyncio.run(Reflector().evaluate(goal="Inspect workspace", plan=make_plan(), result=result))

    assert critique.done is False
    assert "error_type=unknown_tool" in "\n".join(critique.issues)
    assert "error_type=validation_failed" in "\n".join(critique.missing_items)
    assert "correct the tool name or arguments" in critique.suggested_next_action


def test_reflector_suggests_tool_selection_for_no_executable_tool() -> None:
    result = ExecutionResult(
        step_results=[
            StepResult(
                step_id="step-1",
                ok=False,
                status="failed",
                error_type="no_executable_tool",
                summary="No executable tool call for step: Read",
            )
        ]
    )

    critique = asyncio.run(Reflector().evaluate(goal="Inspect workspace", plan=make_plan(), result=result))

    assert critique.done is False
    assert "error_type=no_executable_tool" in "\n".join(critique.issues)
    assert "choose suitable registered tools" in critique.suggested_next_action
