from __future__ import annotations

from pydantic import BaseModel


class TokenBudget(BaseModel):
    total: int
    used: int = 0

    @property
    def remaining(self) -> int:
        return max(self.total - self.used, 0)

    def reserve_text(self, text: str) -> str:
        if self.remaining <= 0:
            return ""
        if len(text) <= self.remaining:
            self.used += len(text)
            return text
        clipped = text[: self.remaining]
        self.used = self.total
        return clipped
