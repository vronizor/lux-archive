# Lux Archive — notes for Claude

- Small personal app on joan-pi; keep it small. One container, SQLite, server-rendered Jinja, vanilla JS, no build step.
- Roll IDs are immutable accession numbers. Never renumber, never reuse (`meta.last_issued` guards deletes).
- Stage timestamps (`*_at`) are the progress history; `events` only feeds session inference. Keep both in sync via `db.set_stage`.
- Two visual modes: light = light table (warm paper, amber), dark = darkroom (near-black, safelight red used only as accent, never for body text). All colors are CSS tokens in `static/style.css`.
- Must work well on a phone: the add form is the main mobile path (sticky save bar, autofocus on contents).
- Keep code comments to a minimum. Any Python data transformation uses polars, not pandas (none needed so far).
- Test locally: `DATA_DIR=/tmp/lux python -m uvicorn app.main:app --port 8411`.
- Keyboard shortcuts live in `static/app.js`; the `?` card lists them (global rows in `base.html`, page rows in each page's `keys` block). Add or remove a key in both places so the card never lists a dead key.
