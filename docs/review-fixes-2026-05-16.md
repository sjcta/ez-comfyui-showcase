# Review Fixes — 2026-05-16

## Scope

This batch addresses the highest-risk findings from the v4 pipeline/code review:

- Secret handling and privileged API access
- Job queue concurrency and duplicate cold-start behavior
- User-scoped job/history access
- Missing workflow matching endpoint used by the frontend

## Changes Applied

### Security

- JWT no longer falls back to a fixed production secret. If `JWT_SECRET_KEY` is unset, the app uses an ephemeral startup secret and prints a warning.
- Node SSH credentials can now use `env:VARIABLE_NAME` values in `config/nodes.json`.
- The DGX Spark SSH password entry was changed to `env:DGX_SPARK_SSH_PASSWORD`.
- Privileged API operations now require authentication:
  - ComfyUI/vLLM start-stop operations
  - GPU process kill
  - Workflow sync/upload/delete/config/meta/version mutations
  - Node CRUD/discovery/instance actions
  - Logs
- Frontend fetch calls to same-origin `/api/` routes automatically attach the stored bearer token.

### Queue And Pipeline

- Removed global job semaphore usage from the active dispatch path.
- Jobs now serialize only on the selected ComfyUI instance semaphore.
- Cancel no longer releases an unowned global semaphore.
- Cancel releases an instance semaphore only when the job actually acquired it.
- Instance selection no longer cold-starts every offline instance.
- T2I/I2I routing can choose the intended instance and lets the execution phase cold-start only that selected instance.
- Fixed stale `prompt_id` variable references in `generate_task()`.

### User Data Boundaries

- `/api/jobs` and `/api/jobs/{job_id}` are scoped to the authenticated user.
- Job cancellation and retry verify ownership.
- `/api/history` returns only the authenticated user's records.
- Manual history creation writes the authenticated `user_id`.
- History clear deletes only the authenticated user's database rows.

### Frontend Contract

- Added `/api/workflows/find-closest` to support history/job restoration after workflow renames or metadata changes.
- Fixed the auth module's internal `_api()` helper to use `fetch()` instead of treating `A.API` as a function.

## Validation Checklist

- Python syntax check: `python3 -m py_compile app.py modules/*.py`
- JavaScript syntax check: `node --check static/js/modules/auth.js`
- Static grep:
  - No remaining `_global_sem` references
  - No remaining `prompt_id or` stale references
  - `find-closest` exists in both frontend caller and backend route

## Remaining Work

- Add role-based authorization instead of treating all authenticated users as privileged.
- Finish replacing the legacy inline generation path with `JobRunner + InstanceManager + WSTracker`.
- Move existing local secrets out of any deployed config before production use.
- Continue removing inline styles and emoji icons to fully satisfy `PROJECT_STANDARDS.md`.

## Follow-up Batch

### User And Role Management

- Added `role` and `disabled` columns to the auth database.
- The first registered user is promoted to `admin`; existing installs promote the earliest user if no admin exists.
- JWT payloads now include the current role, and token validation refreshes role/disabled state from SQLite.
- `require_admin` now enforces real administrator permission.
- Added administrator APIs:
  - `GET /api/users`
  - `PUT /api/users/{user_id}`
  - `DELETE /api/users/{user_id}`
- Added self-service password change:
  - `POST /auth/change-password`
- Added account management UI in `auth.js`:
  - Profile/password tab
  - Admin user-management tab
  - Personal history tab

### Personal History And Sharing

- Added `is_public` column to generation history.
- `/api/history` now supports `scope=gallery|mine|public|all`.
- Gallery scope shows the current user's images plus public shared images.
- Added history operations:
  - `POST /api/history/{item_id}/share`
  - `POST /api/history/batch-delete`
  - `POST /api/history/batch-download`
- Account UI supports selecting personal history items, batch deleting, batch downloading, and sharing/unsharing to the public gallery.

### V4 Pipeline Takeover

- The queue worker now dispatches through `JobRunner` when initialized.
- `InstanceManager` and `JobRunner` are created during FastAPI lifespan startup.
- The queued job tuple now carries `user_id` into the v4 runner.
- `JobRunner` output persistence was aligned with the app's user/date output layout and SQLite `user_id` writing.
- Legacy `_dispatch_and_run()` remains as a fallback if the v4 runner is unavailable.

### Additional Validation

- Python syntax check: `python3 -m py_compile app.py modules/*.py`
- JavaScript syntax check: `node --check static/js/modules/auth.js`
- FastAPI route import check confirmed:
  - `/api/users`
  - `/auth/change-password`
  - `/api/history/batch-delete`
  - `/api/history/batch-download`
  - `/api/workflows/find-closest`
