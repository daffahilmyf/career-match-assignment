from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Iterable, Protocol, Type, runtime_checkable

from pydantic import BaseModel

from pelgo.domain.model import tool_schema


@runtime_checkable
class Tool(Protocol):
    name: ClassVar[str]
    input_model: ClassVar[Type[BaseModel]]
    output_model: ClassVar[Type[BaseModel]]

    def __call__(self, payload: BaseModel) -> BaseModel: ...


ToolRegistry = dict[str, Tool]


@dataclass(frozen=True)
class ToolSpec:
    input_model: Type[BaseModel]
    output_model: Type[BaseModel]


REQUIRED_TOOLS: dict[str, ToolSpec] = {
    "extract_jd_requirements": ToolSpec(
        input_model=tool_schema.ExtractJDRequirementsInput,
        output_model=tool_schema.ExtractJDRequirementsOutput,
    ),
    "score_candidate_against_requirements": ToolSpec(
        input_model=tool_schema.ScoreCandidateInput,
        output_model=tool_schema.ScoreCandidateOutput,
    ),
    "research_skill_resources": ToolSpec(
        input_model=tool_schema.ResearchSkillResourcesInput,
        output_model=tool_schema.ResearchSkillResourcesOutput,
    ),
    "prioritise_skill_gaps": ToolSpec(
        input_model=tool_schema.PrioritiseSkillGapsInput,
        output_model=tool_schema.PrioritiseSkillGapsOutput,
    ),
}


def build_tool_registry(tools: Iterable[Tool]) -> ToolRegistry:
    return {tool.name: tool for tool in tools}


def validate_tool_registry(tools: ToolRegistry) -> None:
    missing = [name for name in REQUIRED_TOOLS if name not in tools]
    if missing:
        raise ValueError(f"Missing required tools: {', '.join(missing)}")

    for name, spec in REQUIRED_TOOLS.items():
        tool = tools[name]
        if tool.input_model is not spec.input_model:
            raise TypeError(
                f"Tool '{name}' input_model mismatch: "
                f"expected {spec.input_model.__name__}, got {tool.input_model.__name__}"
            )
        if tool.output_model is not spec.output_model:
            raise TypeError(
                f"Tool '{name}' output_model mismatch: "
                f"expected {spec.output_model.__name__}, got {tool.output_model.__name__}"
            )
