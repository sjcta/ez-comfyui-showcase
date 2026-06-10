#!/usr/bin/env python3
"""Consolidate database-backed media into canonical storage roots.

Canonical roots:
- generated images and thumbnails: data/outputs/{user}/{date}/{file}
- input/reference images: data/input/{user}/{date}/{file}

This script intentionally fixes stored data and files instead of relying on
runtime fallback reads from legacy folders.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path


BASE = Path(__file__).resolve().parents[1]
DATA = BASE / "data"
GEN_DB = DATA / "generation.db"
HISTORY_JSON = DATA / "history" / "history.json"
INPUT_DIR = DATA / "input"
UPLOADS_DIR = DATA / "uploads"
OUTPUT_DIR = DATA / "outputs"
HISTORY_DIR = DATA / "history"
BACKUP_DIR = DATA / "migration_backups"
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def norm_rel(value: str) -> str:
    return str(value or "").replace("\\", "/").lstrip("/")


def is_image(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in IMAGE_EXTS


def is_canonical_rel(value: str) -> bool:
    parts = norm_rel(value).split("/")
    return len(parts) >= 3 and bool(parts[0]) and bool(DATE_RE.match(parts[1])) and bool(parts[-1])


def clean_user(value: str) -> str:
    value = str(value or "").strip() or "legacy"
    value = re.sub(r"[^A-Za-z0-9_.-]+", "_", value)
    return value[:80] or "legacy"


def date_from_text(value: str) -> str:
    match = re.search(r"\d{4}-\d{2}-\d{2}", str(value or ""))
    return match.group(0) if match else datetime.now().strftime("%Y-%m-%d")


def target_rel(current: str, user_id: str, created_at: str) -> str:
    current = norm_rel(current)
    if is_canonical_rel(current):
        return current
    return f"{clean_user(user_id)}/{date_from_text(created_at)}/{Path(current).name}"


def index_images(*roots: Path) -> dict[str, list[Path]]:
    index: dict[str, list[Path]] = defaultdict(list)
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if is_image(path):
                index[path.name].append(path)
    return index


def backup_files(dry_run: bool) -> None:
    if dry_run:
        return
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = BACKUP_DIR / stamp
    dest.mkdir(parents=True, exist_ok=True)
    for path in (GEN_DB, HISTORY_JSON):
        if path.exists():
            shutil.copy2(path, dest / path.name)


def move_file(src: Path, dst: Path, dry_run: bool) -> None:
    if src.resolve() == dst.resolve():
        return
    if dry_run:
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        return
    shutil.move(str(src), str(dst))


def choose_source(rel: str, canonical_root: Path, legacy_roots: list[Path], index: dict[str, list[Path]]) -> Path | None:
    rel = norm_rel(rel)
    direct = canonical_root / rel
    if direct.is_file():
        return direct
    for root in legacy_roots:
        candidate = root / rel
        if candidate.is_file():
            return candidate
    basename = Path(rel).name
    matches = [
        path for path in index.get(basename, [])
        if path.is_file() and any(root in path.parents or path == root for root in [canonical_root, *legacy_roots])
    ]
    if len(matches) == 1:
        return matches[0]
    return None


def load_rows() -> list[sqlite3.Row]:
    conn = sqlite3.connect(GEN_DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, user_id, created_at, image_path, thumb_path, params FROM generations ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return rows


def reconcile_db(dry_run: bool) -> dict:
    rows = load_rows()
    output_index = index_images(OUTPUT_DIR, HISTORY_DIR)
    input_index = index_images(INPUT_DIR, UPLOADS_DIR)
    report = {
        "rows": len(rows),
        "db_rows_changed": 0,
        "output_files_moved": 0,
        "input_files_moved": 0,
        "missing_outputs": [],
        "missing_inputs": [],
        "noncanonical_refs": [],
    }
    updates: list[tuple[str, str, str, str]] = []

    for row in rows:
        image_rel = target_rel(row["image_path"], row["user_id"], row["created_at"])
        thumb_rel = target_rel(row["thumb_path"], row["user_id"], row["created_at"])
        for rel in (image_rel, thumb_rel):
            if not rel:
                continue
            src = choose_source(rel, OUTPUT_DIR, [HISTORY_DIR], output_index)
            dst = OUTPUT_DIR / rel
            if src and not dst.is_file():
                move_file(src, dst, dry_run)
                report["output_files_moved"] += 1
            if not src and not dst.is_file():
                report["missing_outputs"].append({"id": row["id"], "path": rel})

        try:
            params = json.loads(row["params"] or "{}")
        except Exception:
            params = {}
        params_changed = False
        for key, value in list(params.items()):
            if not str(key).endswith("::image") or not value:
                continue
            rel = target_rel(str(value), row["user_id"], row["created_at"])
            if rel != norm_rel(str(value)):
                params[key] = rel
                params_changed = True
                report["noncanonical_refs"].append({"id": row["id"], "field": key, "path": value, "fixed": rel})
            src = choose_source(rel, INPUT_DIR, [UPLOADS_DIR], input_index)
            dst = INPUT_DIR / rel
            if src and not dst.is_file():
                move_file(src, dst, dry_run)
                report["input_files_moved"] += 1
            if not src and not dst.is_file():
                report["missing_inputs"].append({"id": row["id"], "field": key, "path": rel})

        row_changed = (
            image_rel != norm_rel(row["image_path"])
            or thumb_rel != norm_rel(row["thumb_path"])
            or params_changed
        )
        if row_changed:
            report["db_rows_changed"] += 1
            updates.append((image_rel, thumb_rel, json.dumps(params, ensure_ascii=False), row["id"]))

    if updates and not dry_run:
        conn = sqlite3.connect(GEN_DB)
        conn.executemany("UPDATE generations SET image_path=?, thumb_path=?, params=? WHERE id=?", updates)
        conn.commit()
        conn.close()
    return report


def update_history_json(dry_run: bool) -> int:
    if not HISTORY_JSON.exists():
        return 0
    conn = sqlite3.connect(GEN_DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT id, image_path, thumb_path, params FROM generations").fetchall()
    conn.close()
    by_id = {row["id"]: row for row in rows}
    with HISTORY_JSON.open("r", encoding="utf-8") as fh:
        records = json.load(fh)
    changed = 0
    for item in records if isinstance(records, list) else []:
        row = by_id.get(item.get("id"))
        if not row:
            continue
        item_changed = False
        if item.get("filename") != row["image_path"]:
            item["filename"] = row["image_path"]
            item_changed = True
        if item.get("thumb") != row["thumb_path"]:
            item["thumb"] = row["thumb_path"]
            item_changed = True
        try:
            params = json.loads(row["params"] or "{}")
        except Exception:
            params = {}
        if item.get("field_values") != params:
            item["field_values"] = params
            item_changed = True
        if item_changed:
            changed += 1
    if changed and not dry_run:
        with HISTORY_JSON.open("w", encoding="utf-8") as fh:
            json.dump(records, fh, ensure_ascii=False, indent=2)
    return changed


def remove_empty_dirs(root: Path, dry_run: bool) -> int:
    if not root.exists():
        return 0
    removed = 0
    for path in sorted((p for p in root.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
        try:
            next(path.iterdir())
        except StopIteration:
            removed += 1
            if not dry_run:
                path.rmdir()
    return removed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="move files and update stored references")
    args = parser.parse_args()
    dry_run = not args.apply
    backup_files(dry_run)
    report = reconcile_db(dry_run)
    report["history_json_changed"] = update_history_json(dry_run)
    report["empty_dirs_removed"] = sum(remove_empty_dirs(root, dry_run) for root in (HISTORY_DIR, UPLOADS_DIR))
    report["mode"] = "apply" if args.apply else "dry-run"
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
