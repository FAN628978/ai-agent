from agent_system.prompts import PromptRegistry


def test_prompt_registry_loads_and_renders_template(tmp_path) -> None:
    template = tmp_path / "hello.md"
    template.write_text("Hello $name", encoding="utf-8")
    registry = PromptRegistry(template_dir=tmp_path)

    assert registry.load("hello.md") == "Hello $name"
    assert registry.render("hello.md", name="Haitao") == "Hello Haitao"
    assert registry.render("hello.md") == "Hello $name"
