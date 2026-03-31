from pydantic import BaseModel

from pelgo.api.app import _extract_profile_with_llm
from pelgo.domain.model.candidate_profile import CandidateProfile


class FakeLLM:
    def complete_json(self, prompt: str, schema: type[BaseModel]) -> BaseModel:
        assert "Ari Pranata" in prompt
        return schema(
            name="Ari Pranata",
            email="Ari@example.com",
            skills=["Python", "PostgreSQL", "Python"],
            education=["B.Sc Computer Science"],
            experience=["Senior Backend Engineer at HorizonLabs"],
            years_experience=6,
        )


def test_extract_profile_with_llm_normalizes_output() -> None:
    profile = _extract_profile_with_llm("Ari Pranata\nSkills: Python, PostgreSQL", FakeLLM())

    assert profile == CandidateProfile(
        name="Ari Pranata",
        email="ari@example.com",
        skills=["python", "postgresql"],
        education=["B.Sc Computer Science"],
        experience=["Senior Backend Engineer at HorizonLabs"],
        years_experience=6,
    )
