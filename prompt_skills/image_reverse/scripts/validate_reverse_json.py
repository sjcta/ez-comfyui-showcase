#!/usr/bin/env python3
"""Validate a reverse-prompt JSON artifact against the image_reverse skill."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules.image_reverse_skill import validate_reverse_prompt_quality  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("json_path")
    parser.add_argument("--width", type=int, default=0)
    parser.add_argument("--height", type=int, default=0)
    args = parser.parse_args()

    payload = json.loads(Path(args.json_path).read_text(encoding="utf-8"))
    image_size = (args.width, args.height) if args.width and args.height else None
    report = validate_reverse_prompt_quality(payload, image_size=image_size)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())

