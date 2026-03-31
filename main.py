from __future__ import annotations

import argparse
import json
from pathlib import Path

from pelgo.application.runner import run_once


def _read_text(path: str | None) -> str | None:
    if not path:
        return None
    return Path(path).read_text(encoding="utf-8").strip()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Pelgo agent once")
    parser.add_argument("--candidate-text", type=str, help="Candidate profile text")
    parser.add_argument("--candidate-file", type=str, help="Path to candidate text file")
    parser.add_argument("--jd-text", type=str, help="Job description text")
    parser.add_argument("--jd-file", type=str, help="Path to job description text file")
    parser.add_argument("--jd-url", type=str, help="Job description URL")
    args = parser.parse_args()

    candidate = args.candidate_text or _read_text(args.candidate_file)
    if not candidate:
        raise SystemExit("Provide --candidate-text or --candidate-file")

    jd = args.jd_text or _read_text(args.jd_file) or args.jd_url
    if not jd:
        raise SystemExit("Provide --jd-text, --jd-file, or --jd-url")

    output = run_once(candidate, jd)
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
