# How the archive works

Habits, conventions and rough processes. Items marked *proposed* are defaults to try, not settled rules.

[TOC]

## One roll, start to finish

1. **File.** The roll gets the next free number, goes into the next sleeve of the current binder, and gets a season and a few words of contents.
2. **Contact sheet.** Photograph the sleeve on the light table and upload it on the roll's page. Every roll gets one, including rolls a lab already scanned. It's how you check the lab didn't skip frames.
3. **Link.** Download `V012_contact.jpg` from the roll page, put it in the roll's digiKam folder, tick *Linked*. From then on the roll exists in digiKam even if nothing else is ever scanned.
4. **Review.** Look at the contact sheet and write down the frames worth scanning, or `0` for none, or `all`.
5. **Scan.** Whenever, in any order, a few frames at a time. Each scan goes straight into the roll's digiKam folder; tap the frame on the roll page.

A roll counts as **done** after step 4. Scanning keeps its own count (frames left to scan), so a roll with nothing worth scanning still finishes.

## Conventions

| What | Convention |
| --- | --- |
| Roll ID | `V001`, `V002`… Accession order, not shooting order. Never renumbered, never reused. |
| Dates | Season + year. Winter YYYY = Dec YYYY – Feb YYYY+1. Tick *Year TBC* when the year is a guess. |
| Where | Binder + sleeve number. One roll per sleeve. |
| Frame numbers | As printed on the film edge: `00`, `0`, `1` … `36`. Half frames get an `A`: `14A`. Never the scan order. |
| Contact sheet file | `V012_contact.jpg` (positive). The negative is `V012_contact_neg.jpg` if you ever want it. |
| Scan files | `V012_14.jpg`, `V012_14A.jpg`. A re-scan of the same frame: `V012_14_v2.jpg` *(proposed)*. |
| digiKam folders | One folder per roll, named after the roll ID: `V012/` *(proposed)*. |
| Lab scans | Put the lab's folder name in *Lab scan folder*. When linking, rename the files to `V012_FF` by matching them against the contact sheet, then set scans to `all`. |

### Writing picks

- `4, 9, 17-19, 22A`: a list; ranges and spaces are fine.
- `0` (or `none`): nothing worth scanning.
- `all`: the whole roll.
- Blank: not reviewed yet.
- Inside a list, `0` and `00` are real frames: `0, 3` means frames 0 and 3.
- Scanning a frame that isn't in the picks adds it to the picks.

## Shooting a contact sheet

- Light table on, room lights dimmed, so the clear sleeve doesn't pick up reflections.
- Phone parallel to the sleeve, sleeve filling the frame, sleeve flat.
- Lock exposure on the film, not on the bright gaps around it.
- Check the edge numbers are readable before moving on: picks depend on them.
- Upload straight from the phone. The app keeps the full-size original and makes a positive.

The positive is a quick conversion (invert, remove the orange mask, stretch each channel). Good enough to judge frames, not a scan. Set the film type (Colour / B&W / Slide) on the roll: slides aren't inverted, and the conversion is redone when you change it.

## Scanning

- Scan all the picks from one roll in one sitting rather than a frame at a time; every extra trip out of the sleeve is a chance for dust and scratches.
- Handle strips by the edges; blow dust off before scanning.
- After a sitting, tap the scanned frames on the roll page (or type them), then *Save scans*.

## Twenty-minute sessions

Small units that each move a counter on the home page:

- file the rolls from one envelope;
- shoot contact sheets for one binder page;
- link a batch of contact sheets in digiKam;
- review five contact sheets;
- scan the picks of one roll.

## Where things live

- **Index:** SQLite on the Pi. Exported every night to the private `lux-archive-data` repo (`rolls.csv`, `events.csv`).
- **Contact sheets:** full-size originals in `data/photos/originals/`, a 3200 px preview and its positive in `data/photos/`. Only the previews go to the nightly backup: the originals are too big for git. *Until the NAS is up, the originals exist only on the Pi's SSD.*
- **digiKam:** contact sheets and scans, one folder per roll. Getting a contact sheet there is manual for now: download from the roll page, drop it in the folder, tick *Linked*.
