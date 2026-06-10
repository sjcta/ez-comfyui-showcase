#!/usr/bin/env python3
"""Organize image assets into {user}/{date}/{file} paths and update references."""

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


def is_user_date_rel(rel: str) -> bool:
    parts = norm_rel(rel).split("/")
    return len(parts) >= 3 and bool(parts[0]) and bool(DATE_RE.match(parts[1]))


def clean_user(value: str) -> str:
    value = str(value or "").strip() or "legacy"
    value = re.sub(r"[^A-Za-z0-9_.-]+", "_", value)
    return value[:80] or "legacy"


def date_from_text(value: str) -> str:
    text = str(value or "")
    match = re.search(r"\d{4}-\d{2}-\d{2}", text)
    if match:
        return match.group(0)
    return ""


def file_date(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d")


def unique_dest(root: Path, rel: str, source: Path) -> Path:
    dest = root / rel
    if not dest.exists() or dest.resolve() == source.resolve():
        return dest
    stem = dest.stem
    suffix = dest.suffix
    parent = dest.parent
    idx = 2
    while True:
        candidate = parent / f"{stem}_{idx}{suffix}"
        if not candidate.exists() or candidate.resolve() == source.resolve():
            return candidate
        idx += 1


def safe_move(source: Path, dest: Path, dry_run: bool) -> None:
    if source.resolve() == dest.resolve():
        return
    if dry_run:
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(dest))


def backup_files(dry_run: bool) -> None:
    if dry_run:
        return
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = BACKUP_DIR / stamp
    dest.mkdir(parents=True, exist_ok=True)
    for path in (GEN_DB, HISTORY_JSON):
        if path.exists():
            shutil.copy2(path, dest / path.name)


def load_generation_rows() -> list[sqlite3.Row]:
    conn = sqlite3.connect(GEN_DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, user_id, created_at, image_path, thumb_path, params FROM generations"
    ).fetchall()
    conn.close()
    return rows


def build_generation_context(rows: list[sqlite3.Row]) -> tuple[dict[str, dict], dict[str, dict]]:
    output_refs: dict[str, dict] = {}
    input_refs: dict[str, dict] = {}
    for row in rows:
        user = clean_user(row["user_id"])
        date = date_from_text(row["created_at"])
        ctx = {"user": user, "date": date, "row_id": row["id"]}
        for key in ("image_path", "thumb_path"):
            rel = norm_rel(row[key])
            if rel:
                output_refs.setdefault(rel, ctx)
        try:
            params = json.loads(row["params"] or "{}")
        except Exception:
            params = {}
        for value_key, value in params.items():
            if str(value_key).endswith("::image") and value:
                input_refs.setdefault(norm_rel(str(value)), ctx)
    return output_refs, input_refs


def load_history_records() -> list[dict]:
    if not HISTORY_JSON.exists():
        return []
    with HISTORY_JSON.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    return data if isinstance(data, list) else []


def history_context(records: list[dict]) -> dict[str, dict]:
    refs: dict[str, dict] = {}
    for item in records:
        user = clean_user(item.get("user_id", ""))
        date = date_from_text(item.get("time", ""))
        ctx = {"user": user, "date": date, "row_id": item.get("id", "")}
        for key in ("filename", "thumb"):
            rel = norm_rel(item.get(key, ""))
            if rel:
                refs.setdefault(rel, ctx)
        fields = item.get("field_values") or {}
        if isinstance(fields, dict):
            for field_key, value in fields.items():
                if str(field_key).endswith("::image") and value:
                    refs.setdefault(norm_rel(str(value)), ctx)
    return refs


def index_files(root: Path) -> dict[str, list[Path]]:
    found: dict[str, list[Path]] = defaultdict(list)
    if not root.exists():
        return found
    for path in root.rglob("*"):
        if is_image(path):
            found[path.name].append(path)
    return found


def context_for_rel(rel: str, source: Path, refs: dict[str, dict]) -> dict:
    rel = norm_rel(rel)
    ctx = refs.get(rel) or refs.get(source.name) or {}
    user = clean_user(ctx.get("user", "legacy"))
    date = ctx.get("date") or file_date(source)
    return {"user": user, "date": date}


def target_rel(rel: str, source: Path, refs: dict[str, dict]) -> str:
    rel = norm_rel(rel)
    if is_user_date_rel(rel):
        return rel
    ctx = context_for_rel(rel, source, refs)
    return f"{ctx['user']}/{ctx['date']}/{source.name}"


def migrate_tree(root: Path, refs: dict[str, dict], dry_run: bool) -> dict[str, str]:
    mapping: dict[str, str] = {}
    if not root.exists():
        return mapping
    files = [path for path in root.rglob("*") if is_image(path)]
    for source in files:
        old_rel = source.relative_to(root).as_posix()
        new_rel = target_rel(old_rel, source, refs)
        dest = unique_dest(root, new_rel, source)
        new_rel = dest.relative_to(root).as_posix()
        if old_rel != new_rel:
            mapping[old_rel] = new_rel
            mapping.setdefault(source.name, new_rel)
            safe_move(source, dest, dry_run)
        else:
            mapping.setdefault(old_rel, old_rel)
            mapping.setdefault(source.name, old_rel)
    return mapping


def update_generation_db(output_map: dict[str, str], input_map: dict[str, str], dry_run: bool) -> int:
    conn = sqlite3.connect(GEN_DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT id, image_path, thumb_path, params FROM generations").fetchall()
    changed = 0
    for row in rows:
        image_path = output_map.get(norm_rel(row["image_path"]), norm_rel(row["image_path"]))
        thumb_path = output_map.get(norm_rel(row["thumb_path"]), norm_rel(row["thumb_path"]))
        try:
            params = json.loads(row["params"] or "{}")
        except Exception:
            params = {}
        params_changed = False
        for key, value in list(params.items()):
            if str(key).endswith("::image") and value:
                rel = norm_rel(str(value))
                next_rel = input_map.get(rel) or input_map.get(os.path.basename(rel))
                if next_rel and next_rel != rel:
                    params[key] = next_rel
                    params_changed = True
        if image_path != norm_rel(row["image_path"]) or thumb_path != norm_rel(row["thumb_path"]) or params_changed:
            changed += 1
            if not dry_run:
                conn.execute(
                    "UPDATE generations SET image_path=?, thumb_path=?, params=? WHERE id=?",
                    (image_path, thumb_path, json.dumps(params, ensure_ascii=False), row["id"]),
                )
    if not dry_run:
        conn.commit()
    conn.close()
    return changed


def update_history_json(output_map: dict[str, str], input_map: dict[str, str], dry_run: bool) -> int:
    records = load_history_records()
    changed = 0
    for item in records:
        item_changed = False
        for key in ("filename", "thumb"):
            rel = norm_rel(item.get(key, ""))
            if rel and output_map.get(rel) and output_map[rel] != rel:
                item[key] = output_map[rel]
                item_changed = True
        fields = item.get("field_values") or {}
        if isinstance(fields, dict):
            for field_key, value in list(fields.items()):
                if str(field_key).endswith("::image") and value:
                    rel = norm_rel(str(value))
                    next_rel = input_map.get(rel) or input_map.get(os.path.basename(rel))
                    if next_rel and next_rel != rel:
                        fields[field_key] = next_rel
                        item_changed = True
        if item_changed:
            changed += 1
    if changed and not dry_run:
        with HISTORY_JSON.open("w", encoding="utf-8") as fh:
            json.dump(records, fh, ensure_ascii=False, indent=2)
    return changed


def remove_empty_dirs(root: Path, dry_run: bool) -> int:
    removed = 0
    if not root.exists():
        return removed
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
    parser.add_argument("--apply", action="store_true", help="move files and update references")
    args = parser.parse_args()
    dry_run = not args.apply

    rows = load_generation_rows()
    output_refs, input_refs = build_generation_context(rows)
    hist_records = load_history_records()
    hist_refs = history_context(hist_records)
    output_refs.update({k: v for k, v in hist_refs.items() if k not in output_refs})
    input_refs.update({k: v for k, v in hist_refs.items() if k not in input_refs})

    backup_files(dry_run)
    input_map = migrate_tree(INPUT_DIR, input_refs, dry_run)
    uploads_map = migrate_tree(UPLOADS_DIR, input_refs, dry_run)
    for old, new in uploads_map.items():
        input_map.setdefault(old, new)
    output_map = migrate_tree(OUTPUT_DIR, output_refs, dry_run)
    history_map = migrate_tree(HISTORY_DIR, output_refs, dry_run)
    for old, new in history_map.items():
        output_map.setdefault(old, new)

    db_changed = update_generation_db(output_map, input_map, dry_run)
    json_changed = update_history_json(output_map, input_map, dry_run)
    empty_dirs = 0
    for root in (INPUT_DIR, UPLOADS_DIR, OUTPUT_DIR, HISTORY_DIR):
        empty_dirs += remove_empty_dirs(root, dry_run)

    moved = {
        "input": sum(1 for old, new in input_map.items() if old != new and "/" in new),
        "uploads": sum(1 for old, new in uploads_map.items() if old != new and "/" in new),
        "outputs": sum(1 for old, new in output_map.items() if old != new and "/" in new),
        "history": sum(1 for old, new in history_map.items() if old != new and "/" in new),
    }
    print(json.dumps({
        "mode": "apply" if args.apply else "dry-run",
        "moved_refs": moved,
        "generation_rows_changed": db_changed,
        "history_records_changed": json_changed,
        "empty_dirs": empty_dirs,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
