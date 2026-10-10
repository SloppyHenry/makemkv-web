"""Auftragsliste aufräumen: beendete Einträge (fertig, übersprungen, abgebrochen, Fehler) ohne Rückfrage entfernen.

Nur Einträge der Liste verschwinden; Dateien, Sperren und laufende Aufträge bleiben unberührt.
"""
from fastapi import APIRouter, HTTPException

from app import ext
from app.state import broadcast, conversions, uploads

router = APIRouter()
ext.allow_proxy(r"conversions/\d+/dismiss")
ext.allow_proxy(r"uploads/\d+/dismiss")
ext.allow_proxy(r"jobs/dismiss-finished")

CV_FINISHED = ("done", "skipped", "cancelled", "error")
UP_FINISHED = ("done", "error")


def _remove(items: list, item_id: int, finished: tuple, what: str) -> None:
    item = next((x for x in items if x["id"] == item_id), None)
    if item is None:
        raise HTTPException(404, f"{what} nicht (mehr) in der Liste")
    if item["status"] not in finished:
        raise HTTPException(409, f"{what} läuft noch oder wartet – erst abbrechen oder überspringen")
    items.remove(item)
    broadcast()


@router.post("/api/conversions/{cid}/dismiss")
async def api_conv_dismiss(cid: int):
    _remove(conversions, cid, CV_FINISHED, "Konvertierung")
    return {"ok": True}


@router.post("/api/uploads/{uid}/dismiss")
async def api_upload_dismiss(uid: int):
    _remove(uploads, uid, UP_FINISHED, "Übertragung")
    return {"ok": True}


@router.post("/api/jobs/dismiss-finished")
async def api_dismiss_finished():
    """Alle beendeten Einträge dieses Rechners entfernen."""
    n = len(conversions) + len(uploads)
    conversions[:] = [c for c in conversions if c["status"] not in CV_FINISHED]
    uploads[:] = [u for u in uploads if u["status"] not in UP_FINISHED]
    removed = n - len(conversions) - len(uploads)
    if removed:
        broadcast()
    return {"ok": True, "removed": removed}
