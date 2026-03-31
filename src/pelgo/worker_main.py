from __future__ import annotations

from pelgo.application.config import AppSettings
from pelgo.application.services.worker import run_worker_loop


def main() -> None:
    settings = AppSettings()
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL must be set to run the worker")
    run_worker_loop(settings.database_url)


if __name__ == "__main__":
    main()
