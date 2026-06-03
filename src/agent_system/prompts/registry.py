from __future__ import annotations

from pathlib import Path
from string import Template


class PromptRegistry:
    def __init__(self, template_dir: str | Path | None = None) -> None:
        self.template_dir = Path(template_dir) if template_dir else Path(__file__).parent / "templates"

    def load(self, name: str) -> str:
        path = self.template_dir / name
        return path.read_text(encoding="utf-8")

    def render(self, template_name: str, **variables: object) -> str:
        template = Template(self.load(template_name))
        values = {key: str(value) for key, value in variables.items()}
        return template.safe_substitute(values)
