"""Fortschritt je Serie merken (welche Episode kommt als Nächstes?), damit Disc 2 bei der richtigen Folge weitermacht."""
from app.media import store


def key(title: str, year, tmdb) -> str:
    return f"tmdb:{tmdb}" if tmdb else f"{(title or '').strip().lower()}|{year or ''}"


def _data() -> dict:
    return store.load("series.json", {})


def next_episode(k: str, season: int, disc: int | None) -> int | None:
    """Nächste Episode der Staffel (None = unbekannt). Kommt eine frühere Disc nachträglich dran, als schon spätere eingetragen sind, ist der Stand unbrauchbar."""
    rec = (_data().get(k) or {}).get("seasons", {}).get(str(season))
    if not rec:
        return None
    if disc and any(int(d) > disc for d in rec.get("discs", {})):
        return None
    return rec.get("next")


def remember(k: str, season: int, disc: int | None, first: int, last: int) -> dict | None:
    """Fortschritt eintragen; gibt den alten Stand zurück (für Rückgängig)."""
    d = _data()
    ser = d.setdefault(k, {"seasons": {}})
    old = ser["seasons"].get(str(season))
    old = {"next": old.get("next"), "discs": dict(old.get("discs", {}))} if old else None
    rec = ser["seasons"].setdefault(str(season), {"next": 1, "discs": {}})
    rec["next"] = max(rec.get("next") or 1, last + 1)
    if disc:
        rec["discs"][str(disc)] = [first, last]
    store.save("series.json")
    return old


def restore(k: str, season: int, old: dict | None):
    ser = _data().setdefault(k, {"seasons": {}})
    if old is None:
        ser["seasons"].pop(str(season), None)
    else:
        ser["seasons"][str(season)] = old
    store.save("series.json")
