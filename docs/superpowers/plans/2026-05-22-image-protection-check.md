# Image Protection Check Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hold completed images in a checking state until a local lightweight image protection worker writes a safe/protected result.

**Architecture:** Store protection state on generation records, hide pending records from normal history queries, and keep the job card active as "图片校验中". A resident Python worker lazily loads an optional local classifier and falls back to conservative local heuristics without using ComfyUI.

**Tech Stack:** FastAPI, SQLite, asyncio background tasks, Pillow, existing vanilla JS gallery modules, unittest/pytest.

---

### Task 1: Protection State Persistence

**Files:**
- Modify: `app.py`
- Test: `tests/test_history_api.py`

- [ ] Add generation columns `protection_status`, `protection_score`, `protection_reason`, `protection_source`, and `protection_checked_at`.
- [ ] Make `_insert_generation()` default new records to `pending`.
- [ ] Add `_update_generation_protection()` to write completed results.
- [ ] Hide `pending` rows from normal `/api/history` responses while still exposing completed protection fields.

### Task 2: Resident Local Worker

**Files:**
- Create: `modules/image_protection.py`
- Modify: `app.py`
- Test: `tests/test_image_protection.py`

- [ ] Add a resident worker that lazy-loads an optional local classifier once.
- [ ] Keep the worker independent of ComfyUI.
- [ ] Classify thumbnails or low-resolution images first.
- [ ] Fall back to local image heuristics plus prompt signals when no model is configured.

### Task 3: Job Checking State

**Files:**
- Modify: `modules/job_runner.py`
- Modify: `app.py`
- Modify: `static/js/modules/history.js`
- Modify: `static/js/modules/card_manager.js`
- Modify: `static/js/modules/poll_manager.js`

- [ ] After images are saved and records inserted, broadcast `status="checking"` with message `图片校验中`.
- [ ] Schedule the local worker and release the ComfyUI generation path.
- [ ] Broadcast `done` with image data only after protection results are persisted.
- [ ] Render checking cards as placeholders, not real image previews.

### Task 4: Frontend Protection Source

**Files:**
- Modify: `static/js/modules/history.js`
- Modify: `static/js/modules/card_manager.js`
- Modify: `static/js/modules/workflows.js`
- Test: `tests/test_sensitive_preview_keywords.py`

- [ ] Make card blur depend on backend `protection_status === "protected"` or conservative `error`.
- [ ] Keep keyword matching only as a legacy fallback when records do not have a protection status.
- [ ] Use the same backend field contract in history cards, card manager, and workflow previews.

### Task 5: Version And Verification

**Files:**
- Modify: `VERSION`
- Modify: `app.py`
- Modify: `static/index.html`
- Test: `tests/test_app_version.py`

- [ ] Bump from `v4.2.2` to `v4.2.3`.
- [ ] Run focused unit tests for history, protection worker, frontend source checks, and version.
- [ ] Run syntax checks for edited Python and JS modules.
