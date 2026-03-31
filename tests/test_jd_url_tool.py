from pydantic import BaseModel

from pelgo.adapters.tools import tool_suite
from pelgo.adapters.tools.tool_suite import ExtractJDRequirementsTool
from pelgo.domain.model.tool_schema import ExtractJDRequirementsInput, ExtractJDRequirementsOutput


class FakeLLM:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def complete_json(self, prompt: str, schema: type[BaseModel]) -> BaseModel:
        self.prompts.append(prompt)
        return schema(
            required_skills=["python", "aws"],
            nice_to_have_skills=["docker"],
            seniority_level="senior",
            domain="backend",
            responsibilities=["build services"],
        )

    def usage(self):
        return None

    def call_count(self) -> int:
        return len(self.prompts)


class FakeRepository:
    def __init__(self) -> None:
        self.cached = None
        self.upserts: list[tuple[str, str, dict]] = []

    def get_cached_jd(self, jd_url: str):
        return self.cached

    def upsert_cached_jd(self, jd_url: str, content_hash: str, requirements_json: dict) -> None:
        self.upserts.append((jd_url, content_hash, requirements_json))


def test_extract_jd_requirements_supports_url_input(monkeypatch):
    html = """
    <html>
      <body>
        <h1>Senior Backend Engineer</h1>
        <p>Requirements: Python, AWS, Docker</p>
        <p>Build scalable backend services</p>
      </body>
    </html>
    """
    monkeypatch.setattr(tool_suite, "_fetch_url", lambda *_args, **_kwargs: html)

    llm = FakeLLM()
    repo = FakeRepository()
    tool = ExtractJDRequirementsTool(llm=llm, repository=repo)

    output = tool(ExtractJDRequirementsInput(job_url_or_text="https://example.com/jobs/backend"))

    assert isinstance(output, ExtractJDRequirementsOutput)
    assert output.required_skills == ["python", "aws"]
    assert output.seniority_level == "senior"
    assert llm.call_count() == 1
    assert "Senior Backend Engineer" in llm.prompts[0]
    assert "<h1>" not in llm.prompts[0]
    assert repo.upserts
    assert repo.upserts[0][0] == "https://example.com/jobs/backend"
