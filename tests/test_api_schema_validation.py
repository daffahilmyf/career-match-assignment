from __future__ import annotations

import pytest
from pydantic import ValidationError

from pelgo.api.schemas import MatchesCreateRequest
from conftest import ApiTestSettings


@pytest.mark.parametrize(
    ("data", "files", "expected_detail"),
    [
        ({}, None, "Provide exactly one of resume_text or resume_pdf"),
        (
            {"resume_text": "cv text"},
            {"resume_pdf": ("resume.pdf", b"fake", "application/pdf")},
            "Provide exactly one of resume_text or resume_pdf",
        ),
    ],
)
def test_candidate_endpoint_validates_resume_source_exclusivity(
    api_client_factory,
    data,
    files,
    expected_detail,
) -> None:
    client = api_client_factory()

    response = client.post("/api/v1/candidate", data=data, files=files)

    assert response.status_code == 400
    assert response.json()["detail"] == expected_detail


def test_candidate_endpoint_rejects_pdf_larger_than_configured_limit(api_client_factory) -> None:
    client = api_client_factory(settings=ApiTestSettings(candidate_pdf_max_bytes=8))

    response = client.post(
        "/api/v1/candidate",
        files={"resume_pdf": ("resume.pdf", b"123456789", "application/pdf")},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "resume_pdf exceeds max size of 8 bytes"


def test_candidate_endpoint_openapi_documents_mutually_exclusive_sources(api_client_factory) -> None:
    client = api_client_factory()

    operation = client.app.openapi()["paths"]["/api/v1/candidate"]["post"]
    multipart_schema = operation["requestBody"]["content"]["multipart/form-data"]["schema"]

    assert operation["summary"] == "Create candidate from resume text or PDF"
    assert operation["description"] == (
        "Submit exactly one resume source as multipart form data: either `resume_text` "
        "or `resume_pdf`."
    )
    assert multipart_schema["oneOf"] == [
        {
            "type": "object",
            "required": ["resume_text"],
            "properties": {
                "resume_text": {
                    "type": "string",
                    "description": "Plain text resume content.",
                }
            },
        },
        {
            "type": "object",
            "required": ["resume_pdf"],
            "properties": {
                "resume_pdf": {
                    "type": "string",
                    "format": "binary",
                    "description": "PDF resume upload.",
                }
            },
        },
    ]


def test_matches_request_strips_and_validates_jd_sources() -> None:
    payload = MatchesCreateRequest(
        candidate_id="cand-1",
        jd_sources=["  https://example.com/job  ", "Backend engineer\nRequirements: Python"],
    )

    assert payload.jd_sources == [
        "https://example.com/job",
        "Backend engineer\nRequirements: Python",
    ]

    with pytest.raises(ValidationError):
        MatchesCreateRequest(candidate_id="cand-1", jd_sources=["   "])


