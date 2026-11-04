# Lux Archive

The master index of Vincent's film rolls: one record per roll, four stages, and a progress page that makes a 20-minute session feel worth it. Film rolls archive past light; this keeps track of them.

- **Roll IDs** (`V001`, `V002`…) are accession numbers: the next free number, assigned once, never changed or reused. They record when a roll entered the archive, not when it was shot. Chronology lives in the date fields — use *By date* in the index.
- **Stages:** Filed → Photographed (sleeve on a light pad; can be *skipped* for rolls already scanned) → Scanned → Linked (`V###_FF` files in digiKam). Stages can be ticked in any order. A roll is done when all four are ticked or skipped.
- **Seasons:** Winter YYYY = Dec YYYY – Feb YYYY+1.

## Run on the Pi

```bash
cd ~ && git clone git@github.com:vronizor/lux-archive.git && cd lux-archive
docker compose up -d --build
```

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

*Index → Import CSV.* Columns: `id,start,end,contents,binder,sleeve,stock,camera,scanned`. Dates accept `Summer 2014`, `Su14`, `2014`, and French/Catalan/Spanish season names. Existing IDs are skipped, never overwritten.

## Config

| Variable | Default | |
| --- | --- | --- |
| `APP_NAME` | `Lux Archive` | Display name |
| `LUX_PORT` | `8410` | Host port (localhost only) |
| `BACKUP_DIR` | `../lux-archive-data` | Backup repo checkout, mounted at `/backup` |

## Stack

FastAPI + SQLite + Jinja templates, a little vanilla JS, no build step. The burn-up chart is drawn server-side as SVG.
