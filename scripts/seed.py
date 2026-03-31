from __future__ import annotations

import json
from pathlib import Path

from pelgo.application.config import AppSettings
from pelgo.adapters.persistence.postgres_job_repository import PostgresJobRepository, create_pg_engine


def _load_skills() -> list[str]:
    path = Path("scripts/skills.json")
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    settings = AppSettings()
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL must be set to run seed")

    skills_pool = _load_skills()
    skills = [
        "python",
        "postgresql",
        "aws",
        "docker",
        "kubernetes",
        "fastapi",
        "redis",
        "system design",
    ]
    if skills_pool:
        skills = [skill for skill in skills_pool if skill in skills] + [
            skill for skill in skills_pool if skill not in skills
        ][:4]

    candidate_text = (
        "John Doe\n"
        "Backend Engineer\n"
        "Email: ari.pranata@example.com\n"
        "\n"
        "Summary: Backend engineer with 6+ years building Python services, data pipelines, and cloud deployments. "
        "Focused on reliability, performance, and clean APIs.\n"
        "\n"
        "Skills: Python, FastAPI, PostgreSQL, Redis, Docker, Kubernetes, AWS, Terraform, CI/CD, REST APIs, System Design\n"
        "\n"
        "Experience:\n"
        "- Senior Backend Engineer, HorizonLabs (2022-2026): Led migration to microservices on AWS, built FastAPI services, "
        "and reduced p95 latency by 40%.\n"
        "- Backend Engineer, DataOrbit (2019-2022): Built ETL pipelines with Airflow, optimized Postgres queries, and "
        "implemented caching with Redis.\n"
        "\n"
        "Education:\n"
        "- B.Sc. Computer Science, Bandung Institute of Technology\n"
    )

    job_text = (
        "Senior Backend Engineer\n"
        "We are hiring a Senior Backend Engineer to build scalable APIs and data systems.\n"
        "\n"
        "Requirements:\n"
        "- 5+ years backend development with Python\n"
        "- Strong experience with PostgreSQL and Redis\n"
        "- Cloud experience with AWS, including containerized services\n"
        "- Familiarity with Kubernetes and CI/CD pipelines\n"
        "- Solid system design and API architecture skills\n"
        "\n"
        "Nice to have:\n"
        "- Experience with Terraform\n"
        "- Observability tooling (Prometheus, Grafana)\n"
        "\n"
        "Responsibilities:\n"
        "- Design and implement backend services\n"
        "- Optimize data access and caching\n"
        "- Collaborate with product and data teams\n"
    )

    profile = {
        "name": "John Doe",
        "email": "ari.pranata@example.com",
        "skills": skills,
        "education": ["B.Sc. Computer Science, Bandung Institute of Technology"],
        "experience": [
            "Senior Backend Engineer, HorizonLabs (2022-2026)",
            "Backend Engineer, DataOrbit (2019-2022)",
        ],
        "years_experience": 6,
        "summary": candidate_text,
    }

    engine = create_pg_engine(settings.database_url)
    repo = PostgresJobRepository(engine)
    candidate_id = repo.create_candidate(profile)
    job_id = repo.create_match_job(candidate_id, job_text)

    print(f"Seeded candidate_id={candidate_id} job_id={job_id}")


if __name__ == "__main__":
    main()
