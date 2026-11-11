import re

NONE = "none"
ALL = "all"

_NONE_WORDS = {"none", "nothing", "-", "—", "rien", "res", "nada"}
_ALL_WORDS = {"all", "*", "tout", "tot", "todo", "todos", "whole"}
_TOKEN = re.compile(r"^(\d{1,2})([aA]?)$")
_RANGE = re.compile(r"^(\d{1,2})\s*[-–—]\s*(\d{1,2})$")


def _norm(num, half=""):
    n = "00" if num == "00" else str(int(num))
    return n + half.upper()


def _key(frame):
    m = _TOKEN.match(frame)
    num, half = m.group(1), m.group(2)
    return (-1 if num == "00" else int(num), half)


def parse(text):
    text = (text or "").strip()
    low = text.lower()
    if not text:
        return ""
    if low in _NONE_WORDS:
        return NONE
    if low in _ALL_WORDS:
        return ALL
    out = set()
    for part in re.split(r"[,;\s]+", re.sub(r"\s*[-–—]\s*", "-", text)):
        part = part.strip()
        if not part:
            continue
        if part.lower() in _ALL_WORDS:
            return ALL
        r = _RANGE.match(part)
        if r:
            a, b = sorted((int(r.group(1)), int(r.group(2))))
            if b - a > 45:
                raise ValueError(f"range {part} is too long")
            out.update(str(n) for n in range(a, b + 1))
            continue
        t = _TOKEN.match(part)
        if not t:
            raise ValueError(f"“{part}” is not a frame number")
        out.add(_norm(t.group(1), t.group(2)))
    return sorted(out, key=_key) if out else ""


def fmt(value):
    if value in ("", NONE, ALL):
        return value
    out, run = [], []

    def flush():
        if len(run) >= 3:
            out.append(f"{run[0]}–{run[-1]}")
        else:
            out.extend(run)

    for f in value:
        if run and f.isdigit() and run[-1].isdigit() and int(f) == int(run[-1]) + 1 and run[-1] != "00":
            run.append(f)
        else:
            flush()
            run = [f] if f.isdigit() and f != "00" else []
            if not run:
                out.append(f)
    flush()
    return ", ".join(out)


def load(text):
    try:
        return parse(text)
    except ValueError:
        return ""


def combine(picks, scans):
    if scans == NONE:
        scans = ""
    if picks == NONE and scans:
        picks = ""
    if scans == ALL:
        picks = ALL
    if isinstance(picks, list) and isinstance(scans, list):
        picks = sorted(set(picks) | set(scans), key=_key)
    elif picks == "" and isinstance(scans, list) and scans:
        picks = list(scans)
    return picks, scans


def complete(picks, scans):
    if picks in ("", NONE):
        return False
    if scans == ALL:
        return True
    if picks == ALL:
        return False
    return bool(scans) and set(picks) <= set(scans or [])


def remaining(picks, scans):
    if not isinstance(picks, list):
        return []
    done = set(scans) if isinstance(scans, list) else set()
    return [f for f in picks if f not in done]


def state(picks_text, scans_text):
    picks, scans = load(picks_text), load(scans_text)
    if picks == "":
        return "todo"
    if picks == NONE:
        return "skip"
    return "done" if complete(picks, scans) else "part"


def summary(picks_text, scans_text):
    picks, scans = load(picks_text), load(scans_text)
    if picks == "":
        return "to review"
    if picks == NONE:
        return "nothing to scan"
    if picks == ALL:
        return "whole roll scanned" if scans == ALL else "whole roll · not scanned yet"
    n = len(picks)
    left = len(remaining(picks, scans))
    if scans == ALL or not left:
        return f"{n} picked · all scanned"
    return f"{n - left} of {n} scanned"
