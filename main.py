from __future__ import annotations

import json

from pelgo.application.runner import run_once


if __name__ == "__main__":
    candidate = """
    Backend engineer with 5 years of Python experience. Built REST APIs, worked on PostgreSQL, and deployed services on AWS.
    Skills: Python, FastAPI, PostgreSQL, Docker, AWS, CI/CD.
    """.strip()

    jd = """
    We are hiring a Senior Backend Engineer. Required: Python, APIs, PostgreSQL, AWS.
    Nice to have: Kubernetes, Terraform. Responsibilities include building scalable services.
    """.strip()

    output = run_once(candidate, jd)
    print(json.dumps(output, indent=2))
