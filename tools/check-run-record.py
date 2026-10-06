#!/usr/bin/env python3
"""check-run-record.py — verify a run record carries the recovery metrics.

A run closed on or after the recovery must record measured values, not null, for:
started_at, ended_at, total_production_seconds, quality_score, render_retries and
manual_interventions (RUN_METRICS.md §Required for new runs). Read-only.

Usage:  python3 tools/check-run-record.py runs/<run-id>.json
Exit 0 when complete, 1 with one line per problem otherwise.
"""
import json
import sys
from datetime import datetime


def problems(record: dict) -> list:
    out = []
    times = {}
    for key in ("started_at", "ended_at"):
        try:
            times[key] = datetime.fromisoformat(record.get(key))
            if times[key].tzinfo is None:
                out.append("%s needs an explicit UTC offset" % key)
        except (TypeError, ValueError):
            out.append("%s must be an ISO 8601 timestamp" % key)
    total = record.get("total_production_seconds")
    if not isinstance(total, (int, float)) or isinstance(total, bool) or total <= 0:
        out.append("total_production_seconds must be a positive number")
    elif len(times) == 2 and not out:
        span = (times["ended_at"] - times["started_at"]).total_seconds()
        if abs(span - total) > 1:
            out.append("total_production_seconds %s != ended_at - started_at (%s)" % (total, span))
    score = record.get("quality_score")
    if not isinstance(score, (int, float)) or isinstance(score, bool) or not 0 <= score <= 100:
        out.append("quality_score must be a number within 0..100 (visual score from the human review)")
    for key in ("render_retries", "manual_interventions"):
        value = record.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            out.append("%s must be a non-negative integer" % key)
    return out


def main(argv) -> int:
    if len(argv) != 2:
        print(__doc__.strip())
        return 2
    with open(argv[1], encoding="utf-8") as fh:
        found = problems(json.load(fh))
    for line in found:
        print("INCOMPLETE: " + line)
    if not found:
        print("ok")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
