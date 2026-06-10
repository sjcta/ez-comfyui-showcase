#!/usr/bin/env python3
"""Clean up records before 2026-05-06 from V3 and V4."""
import json, os, sys, shutil

CUTOFF = "2026-05-06"

def clean_v3(history_dir):
    """Clean V3 on DGX (JSON-based storage)."""
    json_path = os.path.join(history_dir, "history.json")
    thumb_dir = os.path.join(history_dir, "thumbs")
    
    with open(json_path) as f:
        records = json.load(f)
    
    old_records = [r for r in records if r.get("time", "") < CUTOFF]
    kept_records = [r for r in records if r.get("time", "") >= CUTOFF]
    
    print(f"V3: {len(records)} total → 删 {len(old_records)} → 留 {len(kept_records)}")
    
    # Delete files for old records
    deleted_files = 0
    for r in old_records:
        # Delete image
        fname = r.get("filename", "") or r.get("image", "")
        if fname:
            fp = os.path.join(history_dir, fname)
            if os.path.isfile(fp):
                os.remove(fp)
                deleted_files += 1
        # Delete thumbnail
        thumb_name = r.get("thumb", "")
        if thumb_name:
            tp = os.path.join(thumb_dir, thumb_name)
            if os.path.isfile(tp):
                os.remove(tp)
                deleted_files += 1
    
    # Write back cleaned history.json
    with open(json_path, "w") as f:
        json.dump(kept_records, f, ensure_ascii=False, indent=2)
    
    print(f"  → 删除了 {deleted_files} 个文件")
    return len(old_records), len(kept_records)


def clean_v4(history_dir, gen_db):
    """Clean V4 on Mac mini (SQLite-based storage)."""
    import sqlite3
    
    json_path = os.path.join(history_dir, "history.json")
    thumb_dir = os.path.join(history_dir, "thumbs")
    
    # 1. Read JSON to identify records to delete
    with open(json_path) as f:
        records = json.load(f)
    
    old_records = [r for r in records if r.get("time", "") < CUTOFF]
    kept_records = [r for r in records if r.get("time", "") >= CUTOFF]
    
    old_ids = [r["id"] for r in old_records]
    
    print(f"V4: {len(records)} total → 删 {len(old_records)} → 留 {len(kept_records)}")
    
    # 2. Delete from SQLite
    conn = sqlite3.connect(gen_db)
    cur = conn.execute("SELECT id, image_path, thumb_path FROM generations")
    db_rows = cur.fetchall()
    
    deleted_sql = 0
    for row in db_rows:
        rec_id, img_path, thumb_path = row
        if rec_id in old_ids:
            # Delete image file
            if img_path:
                fp = os.path.join(history_dir, img_path)
                if os.path.isfile(fp):
                    os.remove(fp)
            # Delete thumb file
            if thumb_path:
                tp = os.path.join(thumb_dir, thumb_path)
                if os.path.isfile(tp):
                    os.remove(tp)
            deleted_sql += 1
    
    conn.execute("DELETE FROM generations WHERE id IN ({})".format(
        ",".join("?" * len(old_ids))), old_ids)
    conn.commit()
    conn.close()
    
    # 3. Update history.json
    with open(json_path, "w") as f:
        json.dump(kept_records, f, ensure_ascii=False, indent=2)
    
    print(f"  → SQLite 删除了 {deleted_sql} 条")
    return len(old_records), len(kept_records)


if __name__ == "__main__":
    import subprocess
    
    # V3 on DGX
    print("=" * 40)
    print("清理 V3 (DGX)")
    print("=" * 40)
    result = subprocess.run([
        "ssh", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
        "-o", "ConnectTimeout=5", "-p", "22", "sjcta@10.10.10.75",
        f"python3 -c \"{__import__('inspect').getsource(clean_v3)}\nclean_v3('/home/sjcta/ez-comfyui-showcase/history')\""
    ], capture_output=True, text=True, timeout=30)
    print(result.stdout)
    if result.stderr:
        print("ERR:", result.stderr[-300:])
    
    # V4 locally
    print("=" * 40)
    print("清理 V4 (Mac mini)")
    print("=" * 40)
    base = "/Users/ai/.openclaw/workspace/ez-comfyui-showcase"
    clean_v4(
        os.path.join(base, "data", "history"),
        os.path.join(base, "data", "generation.db")
    )
