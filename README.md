# Lux Archive

The master index of a film archive: one record per roll, four stages, and a progress page that makes a 20-minute session feel worth it. Film rolls archive past light; this keeps track of them.

- **Roll IDs** (`V001`, `V002`…) are accession numbers: the next free number, assigned once, never changed or reused. They record when a roll entered the archive, not when it was shot. Chronology lives in the date fields — use *By date* in the index.
- **Stages:** Filed → Contact sheet (sleeve photographed on the light table; every roll gets one) → Linked (`V###_contact-1.jpg` in digiKam) → Scans. Scans hold the frames worth scanning (`4, 9, 17-19`, `none`, `all`) and the frames scanned so far. A roll is done once the first three are ticked and its picks are decided; scanning keeps its own count and can go on afterwards. Frame numbers are the ones printed on the film edge.
- **Docs** tab: habits, conventions and processes, from `app/docs.md`.
- **Re-file** (Index → *Re-file into a binder*): pick a binder, then tap rolls (or type their numbers) in the order they go in. Each gets the next sleeve (tick *Next roll takes 2 sleeves* for a roll cut into short strips) and is marked filed; `u` undoes. Rolls sharing a binder/sleeve are listed so a transfer can be checked when it's done.
- **Contact sheets** are kept full size in `data/photos/originals/`, plus a preview (full size unless `LUX_PHOTO_MAX` caps it) and a positive made from it (the light table is found by colour and ignored; the clearest film sets black, so the orange mask goes; each channel is then balanced on the median of the frames, so a whole roll averages out neutral; slides are left as is). Bumping `contact.VERSION` drops cached positives at startup; each is rebuilt when its roll page is next opened. A roll can have several sheets (one per sleeve), numbered from 1 and never renumbered; files are `V###-N.jpg`. The roll page shows 2000 px display copies (`_view`, `_vneg`, made with the positive, served with a versioned URL so the browser caches them, and prefetched for the previous and next roll); the loupe fetches the full-size file the first time it is used on a sheet. The roll page offers each full-size positive as `V###_contact-N.jpg` for digiKam. Single-sheet rolls from before this are moved to sheet 1 on startup.
- **Where** (binder/sleeve) only exists for filed rolls: unticking *Filed* clears it. A roll cut short can take two consecutive sleeves (`B2/88–89`).
- **Seasons:** Winter YYYY = Dec YYYY – Feb YYYY+1.
- **Year TBC:** tick it when you're unsure of the year (an unsure season alone doesn't count). The roll still sorts by its best-guess date; *Year TBC* in the index lists them for a later pass.

## Install on your own computer (Mac or Windows)

No server, no terminal. Download the file for your computer from the [latest release](https://github.com/vronizor/lux-archive/releases/latest):

- **Mac with Apple silicon** (2020 or later): `Lux-Archive-mac-apple-silicon.zip`
- **Older Intel Mac:** `Lux-Archive-mac-intel.zip`
- **Windows:** `Lux-Archive-windows.zip`

**Mac:** unzip, drag *Lux Archive* into Applications, double-click it. The app isn't signed with Apple, so the first time macOS refuses: open *System Settings → Privacy & Security*, scroll down, click *Open Anyway*. Once.

**Windows:** unzip the folder somewhere it can stay (Documents, say) and double-click *Lux Archive.exe* inside it. The first time, SmartScreen says "Windows protected your PC": *More info → Run anyway*.

Your browser opens on the archive. The app itself has no window: it runs in the background, with a small icon in the menu bar (Mac) or the notification area (Windows) to open the page again or quit. Double-clicking the app again also brings the page back. Then, in **Settings** (the ⚙):

- **Roll letter** first: rolls are numbered with it (`M001`…) and it can't change once a roll exists.
- **Phone:** turn it on, scan the QR code with the phone on the same Wi-Fi. The phone then shoots contact sheets straight into a roll and shows what's in each camera. It works at home, while the computer is on and the app is running. Away from home it doesn't, unless both devices are on a private network such as Tailscale.
- **Backup:** choose a folder that syncs somewhere (iCloud Drive, Dropbox). Without one, the only copy of your archive is on this computer.
- **Notes** (Field and Docs) are your own pages: *Edit this page* at the bottom of each.

**Updating:** a banner appears when a new version is out. Download it, quit the old one, replace it with the new one. The archive lives in a separate folder (shown in Settings) and is never touched by an update.

Builds are made by `.github/workflows/desktop.yml` for every `v*` tag and attached to that tag's release; each one is started and exercised on a real Mac and Windows machine before it is published (`desktop/smoke.py`).

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

Update: push a release tag (`git tag v1.2 && git push origin v1.2`, or a release on GitHub). The Pi deploys it within 5 minutes and rolls back if it doesn't come up; pushing to `main` alone deploys nothing. By hand on the Pi: `deploy lux`. Don't `git pull` in the Pi's checkout.

Data lives in `./data` (SQLite `lux.db` + `photos/`), which is git-ignored.

## Backup (set this up on day one)

The index is the only complete record of the archive, and it sits on an SD card. A nightly job exports it to a private repo:

```bash
cd ~ && git clone git@github.com:vronizor/lux-archive-data.git
crontab -e
# 30 3 * * * $HOME/lux-archive/scripts/backup.sh >> $HOME/lux-backup.log 2>&1
```

The script writes `rolls.csv`, `events.csv` and the contact-sheet previews (`photos/`, capped at 3200 px) into `../lux-archive-data`, then commits and pushes if anything changed. Full-size originals are not backed up to git (too big); copy `data/photos/originals/` somewhere else (NAS) yourself. Positives are regenerated on restore. The Pi needs push access to that repo (a deploy key with write access works).

Restore into an empty database:

```bash
docker compose exec -T lux python -m app.backup restore /backup
```

## Import rolls numbered on paper

*Index → Import CSV.* Columns: `id,start,end,contents,binder,sleeve,stock,camera,scanned` (`scanned` = a whole-roll scan exists), plus an optional `process` column (`colour`/`C-41`, `B&W`/`N&B`, `slide`/`E-6`). Dates accept `Summer 2014`, `Su14`, `2014`, and French/Catalan/Spanish season names. A `?` anywhere in a date (`Su14?`) or a truthy optional `tbc` column flags the roll as *Year TBC*. Existing IDs are skipped, never overwritten.

## Config

| Variable | Default | |
| --- | --- | --- |
| `APP_NAME` | `Lux Archive` | Display name until one is saved in Settings |
| `LUX_PORT` | `8410` | Host port (localhost only) |
| `LUX_PHOTO_MAX` | `0` | Long edge of contact-sheet previews, in px; `0` keeps them full size. Changing it resizes each sheet when its roll page is next opened. The nightly backup always writes 3200 px copies |
| `BACKUP_DIR` | `../lux-archive-data` | Backup repo checkout, mounted at `/backup` |

Name, roll letter, catalogue name and first binder are edited in the app (⚙ Settings) and stored in the database. `LUX_DESKTOP=1` (set by the desktop launcher, never on the Pi) adds phone pairing, folder backup, the update check, editable Field/Docs and the pairing guard.

## Stack

FastAPI + SQLite + Jinja templates, a little vanilla JS, no build step. The burn-up chart is drawn server-side as SVG.
