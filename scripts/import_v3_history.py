#!/usr/bin/env python3
"""Import V3 history.json into V4 SQLite database."""
import json, sqlite3, os, sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HISTORY_JSON = os.path.join(BASE, "data", "history", "history.json")
GEN_DB = os.path.join(BASE, "data", "generation.db")

# Load history.json
with open(HISTORY_JSON) as f:
    records = json.load(f)

if not isinstance(records, list):
    print(f"ERROR: expected list, got {type(records).__name__}")
    sys.exit(1)

print(f"Loaded {len(records)} records from history.json")

conn = sqlite3.connect(GEN_DB)
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA synchronous=OFF")

# Check if table exists, create if needed
conn.execute("""
    CREATE TABLE IF NOT EXISTS generations (
        id TEXT PRIMARY KEY,
        workflow TEXT NOT NULL,
        workflow_name TEXT DEFAULT '',
        device TEXT DEFAULT '',
        instance TEXT DEFAULT '',
        status TEXT DEFAULT 'done',
        image_path TEXT DEFAULT '',
        thumb_path TEXT DEFAULT '',
        created_at DATETIME DEFAULT (datetime('now','localtime')),
        completed_at DATETIME,
        duration_sec INTEGER DEFAULT 0,
        params TEXT DEFAULT '{}',
        prompt TEXT DEFAULT '',
        width INTEGER DEFAULT 0,
        height INTEGER DEFAULT 0,
        seed INTEGER DEFAULT 0
    )
""")

# Check existing count
existing = conn.execute("SELECT COUNT(*) FROM generations").fetchone()[0]
print(f"Existing records in SQLite: {existing}")

inserted = 0
skipped = 0
for r in records:
    rec_id = r.get("id", "")
    if not rec_id:
        skipped += 1
        continue
    
    # Check if already exists
    row = conn.execute("SELECT id FROM generations WHERE id=?", (rec_id,)).fetchone()
    if row:
        skipped += 1
        continue
    
    filename = r.get("filename", "")
    thumb = r.get("thumb", "")
    workflow = r.get("workflow", "unknown")
    prompt = r.get("prompt", "")
    seed = r.get("seed", 0)
    width = r.get("width", 0)
    height = r.get("height", 0)
    elapsed = r.get("elapsed", 0)
    created_at = r.get("time", "")
    field_values = r.get("field_values", {})
    
    # Format time for SQLite - V3 uses "2026-05-12 19:28:38" format, keep as-is
    if created_at and "T" in created_at:
        created_at = created_at.replace("T", " ")[:19]
    
    conn.execute(
        """INSERT INTO generations
           (id, workflow, image_path, thumb_path, prompt, width, height, seed, duration_sec, created_at, params)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            rec_id,
            workflow,
            filename,
            thumb,
            prompt,
            width,
            height,
            seed,
            elapsed,
            created_at or None,
            json.dumps(field_values, ensure_ascii=False) if field_values else "{}",
        )
    )
    inserted += 1

conn.commit()
conn.close()

print(f"Inserted: {inserted}")
print(f"Skipped (existing/no id): {skipped}")
print(f"Total in SQLite now: {existing + inserted}")
