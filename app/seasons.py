import re

SEASONS = ["Spring", "Summer", "Autumn", "Winter"]

_OFFSET = {"Spring": 30, "Summer": 60, None: 65, "Autumn": 90, "Winter": 120}

_ALIASES = {
    "spring": "Spring", "sp": "Spring", "printemps": "Spring", "primavera": "Spring",
    "summer": "Summer", "su": "Summer", "ete": "Summer", "été": "Summer", "estiu": "Summer", "verano": "Summer",
    "autumn": "Autumn", "fall": "Autumn", "au": "Autumn", "automne": "Autumn", "tardor": "Autumn", "otoño": "Autumn",
    "winter": "Winter", "wi": "Winter", "hiver": "Winter", "hivern": "Winter", "invierno": "Winter",
}


def norm_season(value):
    if not value:
        return None
    return _ALIASES.get(str(value).strip().lower())


def sort_key(year, season):
    if not year:
        return None
    return int(year) * 1000 + _OFFSET.get(season, 65)


def label(year, season, short=False):
    if not year:
        return ""
    if not season:
        return str(year)
    if short:
        return f"{season[:2]}{str(year)[-2:]}"
    return f"{season} {year}"


def span(roll, short=False):
    start = label(roll["start_year"], roll["start_season"], short)
    end = label(roll["end_year"], roll["end_season"], short)
    if not start:
        return "undated"
    if not end or end == start:
        return start
    if short:
        return f"{start}–{end}"
    if roll["start_year"] == roll["end_year"] and roll["start_season"] and roll["end_season"]:
        return f"{roll['start_season']}–{roll['end_season']} {roll['end_year']}"
    return f"{start} – {end}"


def parse(text):
    if not text or not str(text).strip():
        return None, None
    parts = re.findall(r"[^\W\d_]+|\d+", str(text))
    year, season = None, None
    for p in parts:
        if p.isdigit():
            n = int(p)
            year = n if n > 100 else 2000 + n
        else:
            season = norm_season(p) or season
    return year, season
