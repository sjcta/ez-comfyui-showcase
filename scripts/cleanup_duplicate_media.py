#!/usr/bin/env python3
"""Audit and quarantine duplicate media files without breaking referenced paths."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
MEDIA_ROOTS = [DATA / "input", DATA / "uploads", DATA / "outputs"]
DB_PATH = DATA / "generation.db"
HISTORY_JSON = DATA / "history" / "history.json"
JOBS_JSON = DATA / "jobs.json"
QUARANTINE_ROOT = DATA / "media_cleanup_quarantine"


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def media_files() -> list[Path]:
    out: list[Path] = []
    for root in MEDIA_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file():
                out.append(path)
    return out


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def walk_strings(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, str):
        found.append(value)
    elif isinstance(value, dict):
        for item in value.values():
            found.extend(walk_strings(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(walk_strings(item))
    return found


def normalize_ref(value: str) -> set[str]:
    raw = str(value or "").strip()
    if not raw:
        return set()
    raw = raw.split("?", 1)[0]
    raw = raw.removeprefix("/api/output/").removeprefix("/output/")
    raw = raw.removeprefix("data/outputs/")
    refs = {raw}
    if raw.startswith("data/"):
        refs.add(raw.removeprefix("data/input/"))
        refs.add(raw.removeprefix("data/uploads/"))
        refs.add(raw.removeprefix("data/outputs/"))
    return {r for r in refs if r and not r.startswith("/")}


def collect_references() -> tuple[set[str], Counter[str]]:
    refs: set[str] = set()
    sources: Counter[str] = Counter()

    def add(value: str, source: str) -> None:
        for item in normalize_ref(value):
            refs.add(item)
            sources[source] += 1

    if DB_PATH.exists() and DB_PATH.stat().st_size:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            for row in conn.execute("SELECT * FROM generations"):
                for key in row.keys():
                    value = row[key]
                    if value is None:
                        continue
                    if key in {"image_path", "thumb_path"}:
                        add(str(value), f"generation.db:{key}")
                    elif key == "params":
                        try:
                            parsed = json.loads(value or "{}")
                        except Exception:
                            parsed = value
                        for item in walk_strings(parsed):
                            add(item, "generation.db:params")
        finally:
            conn.close()

    for path, source in ((HISTORY_JSON, "history.json"), (JOBS_JSON, "jobs.json")):
        if not path.exists() or not path.stat().st_size:
            continue
        try:
            parsed = json.loads(path.read_text("utf-8"))
        except Exception:
            continue
        for item in walk_strings(parsed):
            add(item, source)

    return refs, sources


def is_referenced(path: Path, refs: set[str]) -> bool:
    relative = rel(path)
    candidates = {
        relative,
        relative.removeprefix("data/input/"),
        relative.removeprefix("data/uploads/"),
        relative.removeprefix("data/outputs/"),
        path.name,
    }
    return any(item in refs for item in candidates)


def keep_key(path: Path, referenced: bool) -> tuple[int, int, str]:
    relative = rel(path)
    if referenced:
        return (0, 0, relative)
    if relative.startswith("data/outputs/") and "/20" in relative:
        return (1, 0, relative)
    if relative.startswith("data/input/"):
        return (2, 0, relative)
    if relative.startswith("data/outputs/"):
        return (3, 0, relative)
    if relative.startswith("data/uploads/legacy/"):
        return (4, 0, relative)
    if relative.startswith("data/uploads/"):
        return (5, 0, relative)
    return (9, 0, relative)


def build_plan() -> dict[str, Any]:
    files = media_files()
    refs, ref_sources = collect_references()
    by_size: dict[int, list[Path]] = defaultdict(list)
    for path in files:
        by_size[path.stat().st_size].append(path)

    groups = []
    for size, same_size in by_size.items():
        if len(same_size) < 2:
            continue
        by_hash: dict[str, list[Path]] = defaultdict(list)
        for path in same_size:
            by_hash[sha256(path)].append(path)
        for digest, paths in by_hash.items():
            if len(paths) < 2:
                continue
            annotated = [(path, is_referenced(path, refs)) for path in paths]
            keep_path, keep_ref = sorted(annotated, key=lambda item: keep_key(item[0], item[1]))[0]
            delete_paths = [path for path, referenced in annotated if path != keep_path and not referenced]
            groups.append(
                {
                    "hash": digest,
                    "size": size,
                    "keep": rel(keep_path),
                    "keep_referenced": keep_ref,
                    "paths": [
                        {"path": rel(path), "referenced": referenced}
                        for path, referenced in sorted(annotated, key=lambda item: rel(item[0]))
                    ],
                    "delete": [rel(path) for path in sorted(delete_paths, key=rel)],
                }
            )

    reclaim = sum(group["size"] * len(group["delete"]) for group in groups)
    return {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "media_files": len(files),
        "reference_count": len(refs),
        "reference_sources": dict(ref_sources),
        "duplicate_groups": len(groups),
        "delete_files": sum(len(group["delete"]) for group in groups),
        "reclaim_bytes": reclaim,
        "reclaim_mib": round(reclaim / 1024 / 1024, 2),
        "groups": groups,
    }


def write_manifest(plan: dict[str, Any], name: str) -> Path:
    out_dir = DATA / "cleanup_manifests"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / name
    path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", "utf-8")
    return path


def apply_quarantine(plan: dict[str, Any]) -> None:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target_root = QUARANTINE_ROOT / stamp
    for group in plan["groups"]:
        for item in group["delete"]:
            src = ROOT / item
            if not src.exists():
                continue
            dst = target_root / item
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
    plan["quarantine_dir"] = rel(target_root)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="move unreferenced duplicates to quarantine")
    args = parser.parse_args()

    plan = build_plan()
    if args.apply:
        apply_quarantine(plan)
        manifest = write_manifest(plan, f"duplicate_media_cleanup_apply_{datetime.now():%Y%m%d_%H%M%S}.json")
    else:
        manifest = write_manifest(plan, f"duplicate_media_cleanup_dry_run_{datetime.now():%Y%m%d_%H%M%S}.json")

    print(json.dumps({k: plan[k] for k in plan if k != "groups"}, ensure_ascii=False, indent=2))
    print(f"manifest={rel(manifest)}")


if __name__ == "__main__":
    main()
