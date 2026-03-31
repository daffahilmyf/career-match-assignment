from __future__ import annotations

from enum import Enum
from typing import Annotated

from pydantic import Field


class ConfidenceLevel(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class ResourceType(str, Enum):
    course = "course"
    project = "project"
    cert = "cert"
    doc = "doc"


ScorePercent = Annotated[int, Field(ge=0, le=100)]
PositiveInt = Annotated[int, Field(ge=1)]
NonNegativeInt = Annotated[int, Field(ge=0)]
