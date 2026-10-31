#!/usr/bin/env python3
"""Submit one job to the reviewed public inbox (employer self-serve, step one)."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tau_job_application.job_submissions import SUBMISSIONS_PATH, add_submission  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--title", required=True)
    parser.add_argument("--company", required=True)
    parser.add_argument("--url", required=True, help="Official HTTPS application URL")
    parser.add_argument("--location", required=True, help='e.g. "Lagos, Nigeria"')
    parser.add_argument("--description", default="")
    args = parser.parse_args()
    try:
        record = add_submission(SUBMISSIONS_PATH, vars(args))
    except ValueError as exc:
        raise SystemExit(f"Rejected: {exc}") from exc
    print(f"Added submission: {record['title']} @ {record['company']} ({record['location']})")


if __name__ == "__main__":
    main()
