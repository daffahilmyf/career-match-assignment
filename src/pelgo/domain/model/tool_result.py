from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel

from .shared_types import NonNegativeInt


class ToolError(BaseModel):
    tool: str
    error_type: str
    message: str
    retryable: bool = False
    details: Optional[dict[str, Any]] = None


class ToolResult(BaseModel):
    tool: str
    status: Literal["success", "error"]
    latency_ms: NonNegativeInt
    output: Optional[Any] = None
    error: Optional[ToolError] = None
