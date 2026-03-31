from __future__ import annotations

import json
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from pelgo.ports.persistence import JDCacheRecord, JobRecord, JobRepositoryPort, MatchListRecord, MatchResultRecord


def create_pg_engine(database_url: str) -> Engine:
    return create_engine(database_url, pool_pre_ping=True)


class PostgresJobRepository(JobRepositoryPort):
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def claim_next_job(self) -> JobRecord | None:
        query = text(
            """
            WITH next_job AS (
              SELECT id
              FROM match_jobs
              WHERE status = 'pending'
                AND next_run_at <= now()
              ORDER BY created_at
              FOR UPDATE SKIP LOCKED
              LIMIT 1
            )
            UPDATE match_jobs
            SET status = 'processing',
                updated_at = now()
            WHERE id IN (SELECT id FROM next_job)
            RETURNING id, candidate_id, jd_source, attempts;
            """
        )
        with self.engine.begin() as conn:
            row = conn.execute(query).mappings().first()
            if not row:
                return None
            return JobRecord(
                id=str(row["id"]),
                candidate_id=str(row["candidate_id"]),
                jd_source=row["jd_source"],
                attempts=row["attempts"],
            )

    def create_candidate(self, profile_json: dict[str, Any]) -> str:
        with self.engine.begin() as conn:
            row = conn.execute(
                text(
                    """
                    INSERT INTO candidates (profile_jsonb)
                    VALUES (CAST(:profile AS JSONB))
                    RETURNING id;
                    """
                ),
                {"profile": json.dumps(profile_json)},
            ).mappings().first()
            if not row:
                raise RuntimeError("Failed to create candidate")
            return str(row["id"])

    def create_match_job(self, candidate_id: str, jd_source: str) -> str:
        with self.engine.begin() as conn:
            row = conn.execute(
                text(
                    """
                    INSERT INTO match_jobs (candidate_id, jd_source)
                    VALUES (:candidate_id, :jd_source)
                    RETURNING id;
                    """
                ),
                {"candidate_id": candidate_id, "jd_source": jd_source},
            ).mappings().first()
            if not row:
                raise RuntimeError("Failed to create match job")
            return str(row["id"])

    def mark_completed(self, job_id: str, output: dict[str, Any], trace: dict[str, Any]) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE match_jobs
                    SET status = 'completed',
                        agent_output_jsonb = CAST(:output AS JSONB),
                        agent_trace_jsonb = CAST(:trace AS JSONB),
                        updated_at = now()
                    WHERE id = :job_id;
                    """
                ),
                {"job_id": job_id, "output": json.dumps(output), "trace": json.dumps(trace)},
            )

    def mark_failed(
        self,
        job_id: str,
        error: str,
        attempts: int,
        retry_after_seconds: int,
        trace: dict[str, Any] | None,
    ) -> None:
        status = "failed" if attempts >= 3 else "pending"
        next_run = "now()" if status == "failed" else f"now() + interval '{retry_after_seconds} seconds'"
        trace_payload = json.dumps(trace) if trace is not None else None
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    f"""
                    UPDATE match_jobs
                    SET status = :status,
                        attempts = attempts + 1,
                        last_error = :error,
                        agent_trace_jsonb = COALESCE(CAST(:trace AS JSONB), agent_trace_jsonb),
                        next_run_at = {next_run},
                        updated_at = now()
                    WHERE id = :job_id;
                    """
                ),
                {"job_id": job_id, "status": status, "error": error, "trace": trace_payload},
            )

    def requeue_job(self, job_id: str) -> bool:
        with self.engine.begin() as conn:
            row = conn.execute(
                text(
                    """
                    UPDATE match_jobs
                    SET status = 'pending',
                        attempts = 0,
                        last_error = NULL,
                        next_run_at = now(),
                        updated_at = now()
                    WHERE id = :job_id
                    RETURNING id;
                    """
                ),
                {"job_id": job_id},
            ).mappings().first()
            return row is not None

    def get_candidate_profile(self, candidate_id: str) -> dict[str, Any]:
        with self.engine.begin() as conn:
            row = conn.execute(
                text("SELECT profile_jsonb FROM candidates WHERE id = :id"),
                {"id": candidate_id},
            ).mappings().first()
            if not row:
                raise RuntimeError("Candidate not found")
            return row["profile_jsonb"]

    def get_match_result(self, job_id: str) -> MatchResultRecord | None:
        with self.engine.begin() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT id,
                           status,
                           last_error,
                           agent_output_jsonb,
                           agent_trace_jsonb
                    FROM match_jobs
                    WHERE id = :job_id;
                    """
                ),
                {"job_id": job_id},
            ).mappings().first()
            if not row:
                return None
            return MatchResultRecord(
                job_id=str(row["id"]),
                status=row["status"],
                agent_output=row["agent_output_jsonb"],
                agent_trace=row["agent_trace_jsonb"],
                last_error=row["last_error"],
            )

    def list_match_jobs(self, limit: int, offset: int, status: str | None) -> list[MatchListRecord]:
        query = """
            SELECT id, status
            FROM match_jobs
        """
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if status:
            query += " WHERE status = :status"
            params["status"] = status
        query += " ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
        with self.engine.begin() as conn:
            rows = conn.execute(text(query), params).mappings().all()
            return [MatchListRecord(job_id=str(row["id"]), status=row["status"]) for row in rows]

    def get_cached_jd(self, jd_url: str) -> JDCacheRecord | None:
        with self.engine.begin() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT jd_url, content_hash, requirements_jsonb
                    FROM jd_cache
                    WHERE jd_url = :jd_url
                      AND (expires_at IS NULL OR expires_at > now());
                    """
                ),
                {"jd_url": jd_url},
            ).mappings().first()
            if not row:
                return None
            return JDCacheRecord(
                jd_url=row["jd_url"],
                content_hash=row["content_hash"],
                requirements_json=row["requirements_jsonb"],
            )

    def upsert_cached_jd(self, jd_url: str, content_hash: str, requirements_json: dict[str, Any]) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO jd_cache (jd_url, content_hash, requirements_jsonb, last_fetched_at, expires_at)
                    VALUES (:jd_url, :content_hash, CAST(:requirements_jsonb AS JSONB), now(), now() + interval '7 days')
                    ON CONFLICT (jd_url) DO UPDATE
                    SET content_hash = EXCLUDED.content_hash,
                        requirements_jsonb = EXCLUDED.requirements_jsonb,
                        last_fetched_at = now(),
                        expires_at = now() + interval '7 days';
                    """
                ),
                {
                    "jd_url": jd_url,
                    "content_hash": content_hash,
                    "requirements_jsonb": json.dumps(requirements_json),
                },
            )
