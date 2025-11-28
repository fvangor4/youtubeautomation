#!/usr/bin/env python3
"""Quick CLI to verify the YouTube API key by reusing the app's search helper."""

import argparse
import json
from pathlib import Path
import sys

# Ensure the repo root is importable when the script is executed from subdirs.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app import (
    DATE_RANGE_OPTIONS,
    DEFAULT_DATE_RANGE,
    DEFAULT_TOPIC,
    TOPIC_FILTERS,
    VALID_DURATION_FILTERS,
    search_youtube,
)  # noqa: E402


def parse_args():
    parser = argparse.ArgumentParser(description="Smoke test YouTube Data API access.")
    parser.add_argument("query", nargs="?", default="", help="Search keywords (leave blank with --topic gaming)")
    parser.add_argument(
        "--date-range",
        choices=list(DATE_RANGE_OPTIONS.keys()),
        default=DEFAULT_DATE_RANGE,
        help="How far back to fetch videos (default: %(default)s)",
    )
    parser.add_argument(
        "--duration",
        choices=list(VALID_DURATION_FILTERS.keys()),
        default="any",
        help="Filter by video duration length (default: %(default)s)",
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=5,
        help="How many items to retrieve (1-25)",
    )
    parser.add_argument(
        "--topic",
        choices=list(TOPIC_FILTERS.keys()),
        default=DEFAULT_TOPIC,
        help="Optional topic filter; gaming allows blank query (default: %(default)s)",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    results, quota_used = search_youtube(
        query=args.query,
        range_key=args.date_range,
        duration=args.duration,
        max_results=args.max_results,
        topic_key=args.topic,
    )
    print(json.dumps({"quotaUsed": quota_used, "items": results}, indent=2))


if __name__ == "__main__":
    main()
