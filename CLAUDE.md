# Lux Archive — notes for Claude

- The Pi deploys release tags on its own: a push to `main` deploys nothing; a new `vX.Y` tag on main is built, checked and rolled back if it fails, within 5 minutes. Tag only when the owner asks for a release. Don't tell the owner to `git pull` on the Pi; by hand it is `deploy lux [REF]`.
- Small personal app on joan-pi; keep it small. One container, SQLite, server-rendered Jinja, vanilla JS, no build step.
- Roll IDs are immutable accession numbers. Never renumber, never reuse (`meta.last_issued` guards deletes).
- Stage timestamps (`*_at`) are the progress history; `events` only feeds session inference. Keep both in sync via `db.set_stage`.
- Two visual modes: light = light table (warm paper, amber), dark = darkroom (near-black, safelight red used only as accent, never for body text). All colors are CSS tokens in `static/style.css`.
- Must work well on a phone: the add form is the main mobile path (sticky save bar, autofocus on contents).
- Keep code comments to a minimum. Any Python data transformation uses polars, not pandas (none needed so far).
- Test locally: `DATA_DIR=/tmp/lux python -m uvicorn app.main:app --port 8411`.
- Keyboard shortcuts live in `static/app.js`; the `?` card lists them (global rows in `base.html`, page rows in each page's `keys` block). Add or remove a key in both places so the card never lists a dead key.
- Other people run it as a desktop app (`desktop/launcher.py`, PyInstaller spec, `.github/workflows/desktop.yml`; a `vX.Y` tag also publishes Mac/Windows builds). Desktop-only behaviour sits behind `db.DESKTOP`; the Pi never sets it. Nothing owner-specific in code or templates: prefix, name, catalogue and first binder come from `db.setting()`.
- `app/docs.md` and `app/field.md` are the owner's pages (Pi only). Desktop builds ship `app/starter/*.md` instead, with `%PREFIX%`, `%CATALOG%`, `%APP%` tokens. A process change goes in both `docs.md` files.
- Must run on Windows: always pass `encoding="utf-8"` when reading or writing text, no `%-d` in strftime.
- Schema changes stay additive (`ADDED_COLUMNS`): desktop users update across several versions at once.
- `/sheets` is the phone path for contact sheets (binder order, one tap per roll). On phones the home page shows cameras and that button first; the progress sections sit in a closed `<details>`.
