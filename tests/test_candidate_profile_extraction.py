from pydantic import BaseModel

from pelgo.api.app import _extract_profile_with_llm
from pelgo.domain.model.candidate_profile import CandidateProfile


class FakeLLM:
    def complete_json(self, prompt: str, schema: type[BaseModel]) -> BaseModel:
        assert "John Doe" in prompt
        return schema(
            name="John Doe",
            email="John@example.com",
            skills=["Python", "PostgreSQL", "Python"],
            education=["B.Sc Computer Science"],
            experience=["Senior Backend Engineer at HorizonLabs"],
            years_experience=6,
        )


def test_extract_profile_with_llm_normalizes_output() -> None:
    profile = _extract_profile_with_llm("John Doe\nSkills: Python, PostgreSQL", FakeLLM())

    assert profile == CandidateProfile(
        name="John Doe",
        email="john@example.com",
        skills=["python", "postgresql"],
        education=["B.Sc Computer Science"],
        experience=["Senior Backend Engineer at HorizonLabs"],
        years_experience=6,
    )
