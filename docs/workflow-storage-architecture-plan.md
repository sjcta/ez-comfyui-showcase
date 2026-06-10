# Workflow Storage Architecture Plan

## Goal

Build a stable multi-user workflow system with clear storage boundaries:

- Workflow content remains file-based.
- Collaboration state becomes database-backed.
- JSON sidecar files become compatibility/export artifacts, not primary state.

## Recommended Source of Truth

### File system owns

- Raw workflow files: `data/workflows/**/*.json`
- Workflow version file payloads
- Generated images, thumbnails, uploaded binaries

### Database owns

- Workflow metadata
  - `name`
  - `tags`
  - `owner_id`
  - `shared`
  - `source`
  - `source_path`
  - `thumbnail`
  - `sort_order`
  - `versions`
  - `active_version`
- Node editor configuration
  - field zone
  - visible state
  - custom label
  - order
- Future multi-user collaboration state
  - per-user preferences
  - audit log
  - optimistic lock/version fields

## Current State

### Already migrated to DB

- Workflow metadata is now stored in `generation.db.workflow_meta`
- `wf_meta.json` is exported from DB for compatibility/debugging

### Still file-backed

- Node editor config under `data/wf_configs`
- Workflow file content
- Workflow directory registry in `wf_dirs.json`

## Why this boundary is the best fit

### Pros

- Preserves native ComfyUI file compatibility
- Easier import/export and remote sync
- Database handles concurrent multi-user collaboration safely
- Clearer operational ownership during debugging

### Avoids

- Full BLOB-style workflow storage in DB
- Complex bidirectional sync between DB payload and editable workflow files
- Making DB the only recovery path for raw workflow content

## Target Data Model

### `workflow_meta`

Primary workflow collaboration state table.

### `workflow_editor_config`

Recommended next table:

- `workflow_filename TEXT NOT NULL`
- `config_scope TEXT NOT NULL DEFAULT 'global'`
- `user_id TEXT DEFAULT ''`
- `config_json TEXT NOT NULL`
- `updated_at DATETIME`
- Primary key recommendation:
  - global config: `(workflow_filename, config_scope, user_id)`

`config_scope` supports:

- `global`: admin-defined shared editor structure
- `user`: per-user custom editor layout

### `workflow_audit_log`

Recommended future table:

- `id`
- `workflow_filename`
- `user_id`
- `action`
- `before_json`
- `after_json`
- `created_at`

Use for:

- share toggle audit
- metadata edits
- editor config edits
- version activation

## Migration Plan

### Phase 1

Done:

- move workflow metadata to SQLite
- keep `wf_meta.json` as exported mirror

Verification:

- share toggle persists after page reload
- DB reflects `shared` updates

### Phase 2

Move node editor config from `data/wf_configs` into SQLite.

Tasks:

- add `workflow_editor_config` table
- migrate existing config files to DB
- switch `/api/workflows/{name}/config` read/write to DB
- optionally export file mirror for debugging only

Verification:

- editor layout survives reload
- config survives account switch as designed
- no data loss when legacy file exists

### Phase 3

Move workflow directory registry to DB or keep file-based intentionally.

Recommendation:

- keep `wf_dirs.json` temporarily if only admins change it rarely
- only migrate if multi-node shared administration becomes complex

Verification:

- startup scan still finds all workflows
- remote sync does not regress

### Phase 4

Add audit and concurrency protection.

Tasks:

- audit log table
- updated_at / revision field on mutable rows
- optional optimistic concurrency check

Verification:

- last-write visibility is explainable
- admin actions are traceable

## Validation Checklist

### Metadata

- toggle share updates DB
- toggle share updates exported JSON mirror
- refresh page preserves state
- normal user sees shared workflows only

### Editor config

- edit zone/label/order persists
- config loads consistently after restart
- migration from legacy file format is lossless

### Versions

- upload version updates DB metadata
- activate version updates DB metadata
- delete version updates DB metadata

### Recovery

- deleting exported JSON mirror does not lose DB state
- rebuilding exported mirror from DB works

## Risks

- legacy file and DB diverge if both remain writable
- migration scripts may silently overwrite newer user state
- future per-user editor config needs explicit precedence rules

## Rules to enforce

- DB is the only writable source for collaboration state
- compatibility JSON files must be export-only
- raw workflow content must not be rewritten unless the user explicitly edits the workflow file itself

## Recommended Next Implementation Step

Implement `workflow_editor_config` migration and switch the node editor API to SQLite.
