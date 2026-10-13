"""Tidy up the job list: remove finished entries (done, skipped, cancelled, error) without asking.

Only list entries disappear; files, locks and running jobs stay untouched.
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
        raise HTTPException(404, f"{what} is no longer in the list")
    if item["status"] not in finished:
        raise HTTPException(409, f"{what} is still running or waiting – cancel or skip it first")
    items.remove(item)
    broadcast()


@router.post("/api/conversions/{cid}/dismiss")
async def api_conv_dismiss(cid: int):
    _remove(conversions, cid, CV_FINISHED, "Conversion")
    return {"ok": True}


@router.post("/api/uploads/{uid}/dismiss")
async def api_upload_dismiss(uid: int):
    _remove(uploads, uid, UP_FINISHED, "Transfer")
    return {"ok": True}


@router.post("/api/jobs/dismiss-finished")
async def api_dismiss_finished():
    """Remove all finished entries of this machine."""
    n = len(conversions) + len(uploads)
    conversions[:] = [c for c in conversions if c["status"] not in CV_FINISHED]
    uploads[:] = [u for u in uploads if u["status"] not in UP_FINISHED]
    removed = n - len(conversions) - len(uploads)
    if removed:
        broadcast()
    return {"ok": True, "removed": removed}
