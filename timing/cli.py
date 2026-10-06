"""CLI for the canonical timing layer.

Usage:
  python3 timing/cli.py providers
  python3 timing/cli.py normalize <response.json> --provider elevenlabs --out <word-timings.json>
  python3 timing/cli.py validate  <word-timings.json>
  python3 timing/cli.py phrases   <word-timings.json> [--out <captions.json>]
  python3 timing/cli.py show      <word-timings.json>

All commands are offline and pure over local files.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from timing import adapter, cache, phrases, schema  # noqa: E402


def _load(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def cmd_providers(_args) -> int:
    print("timing adapters: %s" % ", ".join(adapter.supported()))
    return 0


def cmd_normalize(args) -> int:
    resp = _load(args.input)
    doc = adapter.normalize(args.provider, resp, audio_duration_ms=args.audio_duration_ms)
    if args.out:
        wrote = cache.write(args.out, doc, overwrite=args.force)
        print("wrote %s" % wrote)
    print("provider=%s audio_duration_ms=%d words=%d"
          % (doc["provider"], doc["audio_duration_ms"], len(doc["words"])))
    return 0


def cmd_validate(args) -> int:
    doc = schema.validate(_load(args.input))
    print("valid: provider=%s audio_duration_ms=%d words=%d"
          % (doc["provider"], doc["audio_duration_ms"], len(doc["words"])))
    return 0


def cmd_phrases(args) -> int:
    doc = schema.validate(_load(args.input))
    caps = phrases.to_captions(doc["words"])
    phrases.validate_captions(caps)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(caps, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        print("wrote %s" % args.out)
    for c in caps["captions"]:
        print("%8d-%8d  %s" % (c["start_ms"], c["end_ms"], c["text"]))
    return 0


def cmd_show(args) -> int:
    doc = schema.validate(_load(args.input))
    print("provider=%s audio_duration_ms=%d" % (doc["provider"], doc["audio_duration_ms"]))
    for w in doc["words"]:
        print("%8d-%8d  %s" % (w["start_ms"], w["end_ms"], w["word"]))
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="timing", description="Canonical word-timing layer")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("providers", help="list timing adapters")
    p.set_defaults(func=cmd_providers)

    p = sub.add_parser("normalize", help="normalize a provider response")
    p.add_argument("input")
    p.add_argument("--provider", required=True)
    p.add_argument("--out", default=None)
    p.add_argument("--audio-duration-ms", type=int, default=None)
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_normalize)

    p = sub.add_parser("validate", help="validate a canonical timing file")
    p.add_argument("input")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("phrases", help="group words into caption phrases")
    p.add_argument("input")
    p.add_argument("--out", default=None)
    p.set_defaults(func=cmd_phrases)

    p = sub.add_parser("show", help="print normalized words")
    p.add_argument("input")
    p.set_defaults(func=cmd_show)
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
