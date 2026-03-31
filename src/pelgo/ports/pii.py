from __future__ import annotations

from typing import Any, Protocol


class PIIRedactor(Protocol):
    def redact_text(self, text: str) -> str: ...

    def redact_profile(self, profile: dict[str, Any]) -> dict[str, Any]: ...
