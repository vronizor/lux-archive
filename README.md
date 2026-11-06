# Lux Archive

The master index of Vincent's film rolls: one record per roll, four stages, and a progress page that makes a 20-minute session feel worth it. Film rolls archive past light; this keeps track of them.

- **Roll IDs** (`V001`, `V002`…) are accession numbers: the next free number, assigned once, never changed or reused. They record when a roll entered the archive, not when it was shot. Chronology lives in the date fields — use *By date* in the index.
- **Stages:** Filed → Photographed (sleeve on a light pad; can be *skipped* for rolls already scanned) → Scanned → Linked (`V###_FF` files in digiKam). Stages can be ticked in any order. A roll is done when all four are ticked or skipped.
- **Re-file** (Index → *Re-file into a binder*): pick a binder, then tap rolls (or type their numbers) in the order they go in. Each gets the next sleeve and is marked filed; `u` undoes. Rolls sharing a binder/sleeve are listed so a transfer can be checked when it's done.
- **Sleeve photos** are stored at up to 3200 px on the long edge (`LUX_PHOTO_MAX`), enough to read frames from a 35mm sleeve.
- **Seasons:** Winter YYYY = Dec YYYY – Feb YYYY+1.
- **Year TBC:** tick it when you're unsure of the year (an unsure season alone doesn't count). The roll still sorts by its best-guess date; *Year TBC* in the index lists them for a later pass.

## Run on the Pi

```bash
cd ~ && git clone git@github.com:vronizor/lux-archive-data.git
git clone git@github.com:vronizor/lux-archive.git && cd lux-archive
docker compose up -d --build
```

Clone the data repo first: if `../lux-archive-data` doesn't exist, Docker creates it as an empty root-owned folder and the backup clone then fails.

The app listens on `127.0.0.1:8410` (set `LUX_PORT` in `.env` to change it). Expose it on the tailnet as `photos`, the same way as the other services, e.g.:

```bash
sudo tailscale serve --service=svc:photos --https=443 127.0.0.1:8410
```

Update: `git pull && docker compose up -d --build`.

Data lives in `./data` (SQLite `lux.db` + `photos/`), which is git-ignored.

## Backup (set this up on day one)

The index is the only complete record of the archive, and it sits on an SD card. A nightly job exports it to a private repo:

```bash
cd ~ && git clone git@github.com:vronizor/lux-archive-data.git
crontab -e
# 30 3 * * * $HOME/lux-archive/scripts/backup.sh >> $HOME/lux-backup.log 2>&1
```

The script writes `rolls.csv`, `events.csv` and `photos/` into `../lux-archive-data`, then commits and pushes if anything changed. The Pi needs push access to that repo (a deploy key with write access works).

Restore into an empty database:

```bash
docker compose exec -T lux python -m app.backup restore /backup
```

## Import rolls numbered on paper

*Index → Import CSV.* Columns: `id,start,end,contents,binder,sleeve,stock,camera,scanned`, plus an optional `process` column (`colour`/`C-41`, `B&W`/`N&B`, `slide`/`E-6`). Dates accept `Summer 2014`, `Su14`, `2014`, and French/Catalan/Spanish season names. A `?` anywhere in a date (`Su14?`) or a truthy optional `tbc` column flags the roll as *Year TBC*. Existing IDs are skipped, never overwritten.

## Config

| Variable | Default | |
| --- | --- | --- |
| `APP_NAME` | `Lux Archive` | Display name |
| `LUX_PORT` | `8410` | Host port (localhost only) |
| `LUX_PHOTO_MAX` | `3200` | Long edge of stored sleeve photos, in px |
| `BACKUP_DIR` | `../lux-archive-data` | Backup repo checkout, mounted at `/backup` |

## Stack

FastAPI + SQLite + Jinja templates, a little vanilla JS, no build step. The burn-up chart is drawn server-side as SVG.
