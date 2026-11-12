# How the archive works

Habits, conventions and rough processes. Items marked *proposed* are defaults to try, not settled rules.

[TOC]

## One roll, start to finish

1. **File.** The roll gets the next free number, goes into the next sleeve of the current binder, and gets a season and a few words of contents.
2. **Contact sheet.** Photograph the sleeve on the light table and upload it on the roll's page. Every roll gets one, including rolls a lab already scanned. It's how you check the lab didn't skip frames.
3. **Link.** Download `V012_contact.jpg` from the roll page, put it in the roll's digiKam folder, tick *Linked*. From then on the roll exists in digiKam even if nothing else is ever scanned.
4. **Review.** Look at the contact sheet and write down the frames worth scanning, or `none`, or `all`.
5. **Scan.** Whenever, in any order, a few frames at a time. Each scan goes straight into the roll's digiKam folder; tap the frame on the roll page.

A roll counts as **done** after step 4. Scanning keeps its own count (frames left to scan), so a roll with nothing worth scanning still finishes.

## Before the archive: shooting

New rolls enter Lux Archive when you load them, not when you file them.

1. **Load** (`/load`, from the phone). Camera, stock, and the EI you'll shoot at (blank = box speed). The roll gets the next number on the spot: write it on the canister. Forgot to log it? Tick *Already unloaded*.
   While shooting, jot things down from the roll's *In camera* card on the home page. Type, then tap **+ Contents** for what's on the roll ("Gràcia party", appended with a comma) or **+ Note** for how it was shot ("frames 12–14 overexposed", "tried a red filter", one line each). Enter adds to contents.
2. **Unloaded.** Tap it on the home page. The roll joins the *Next lab batch*, which can sit there for weeks.
3. **Sent.** *Send to lab* marks the whole batch at once, with the lab's name. The batch list shows each roll's EI so you can tell the lab what to push.
4. **Back.** The roll enters the archive, unfiled, and the steps below take over.

Disposable cameras work the same way: load them with the camera as `Disposable` (or its brand) and the stock printed on the box.

Dates fill themselves: loading sets the start season, unloading the end. Rolls that aren't back yet stay out of the archive counts and the progress chart; the index shows them with a tag and the *Not back yet* filter.

## Conventions

| What | Convention |
| --- | --- |
| Roll ID | `V001`, `V002`… Accession order, not shooting order. Never renumbered, never reused. New rolls are numbered at loading, so from now on accession order follows shooting order. |
| EI | The speed the roll was shot at. Blank means box speed. Anything else means the lab pushed or pulled it. |
| Dates | Season + year. Winter YYYY = Dec YYYY – Feb YYYY+1. Tick *Year TBC* when the year is a guess. |
| Where | Binder + sleeve number, only once the roll is filed: unticking *Filed* clears it, and typing a binder on an unfiled roll ticks *Filed*. One roll per sleeve. A roll cut into short strips takes two consecutive sleeves (*Takes 2 sleeves*), shown as `B2/88–89`; keep both in the same binder. |
| Frame numbers | As printed on the film edge: `00`, `0`, `1` … `36`. Half frames get an `A`: `14A`. Never the scan order. |
| Contact sheet file | `V012_contact.jpg` (positive). The negative is `V012_contact_neg.jpg` if you ever want it. |
| Scan files | Frame number exactly as printed, never padded: `V012_00.jpg`, `V012_0.jpg`, `V012_4.jpg`, `V012_14A.jpg`. Padding would turn frame 0 into `00` and collide with the real frame 00. digiKam's natural sort (Settings → Miscellaneous → Behavior) puts `_4` before `_14`. A re-scan of the same frame: `V012_14_v2.jpg` *(proposed)*. |
| digiKam folders | One folder per roll, named after the roll ID: `V012/` *(proposed)*. |
| Lab scans | Put the lab's folder name in *Lab scan folder*. When linking, rename the files to `V012_FF` by matching them against the contact sheet, then set scans to `all`. |

### Writing picks

- `4, 9, 17-19, 22A`: a list; ranges and spaces are fine.
- `none`: nothing worth scanning.
- `all`: the whole roll.
- Blank: not reviewed yet.
- `0` and `00` are real frames, on their own or in a list: `0` means frame 0, not “nothing”.
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
