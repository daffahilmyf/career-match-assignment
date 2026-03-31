from __future__ import annotations

from pelgo.adapters.pii.simple_redactor import SimplePIIRedactor


def test_simple_pii_redactor_redacts_text_identifiers() -> None:
    redactor = SimplePIIRedactor()

    text = (
        "John Doe can be reached at john@example.com or +62 812-3456-7890. "
        "Portfolio: https://example.com and github.com/aripranata"
    )

    result = redactor.redact_text(text)

    assert "john@example.com" not in result
    assert "+62 812-3456-7890" not in result
    assert "https://example.com" not in result
    assert "github.com/aripranata" not in result
    assert "[REDACTED_EMAIL]" in result
    assert "[REDACTED_PHONE]" in result
    assert result.count("[REDACTED_URL]") >= 2


def test_simple_pii_redactor_redacts_profile_but_preserves_matching_signal() -> None:
    redactor = SimplePIIRedactor()
    profile = {
        "name": "John Doe",
        "email": "john@example.com",
        "skills": ["Python", "PostgreSQL", "AWS"],
        "experience": [
            "John Doe led Python backend delivery at Example Corp",
            "Contact: +62 812-3456-7890",
        ],
        "education": ["Bandung Institute of Technology"],
        "years_experience": 6,
        "summary": "John Doe is a backend engineer. Website: https://example.com",
    }

    result = redactor.redact_profile(profile)

    assert result["name"] == "[REDACTED_NAME]"
    assert result["email"] == "[REDACTED_EMAIL]"
    assert result["skills"] == ["Python", "PostgreSQL", "AWS"]
    assert result["years_experience"] == 6
    assert "John Doe" not in result["summary"]
    assert "https://example.com" not in result["summary"]
    assert any("Python" in item for item in result["experience"])
    assert any("[REDACTED_PHONE]" in item for item in result["experience"])
