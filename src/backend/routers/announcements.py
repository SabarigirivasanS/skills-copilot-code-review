"""
Announcements endpoints for the High School Management System API
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..database import announcements_collection, teachers_collection

router = APIRouter(
    prefix="/announcements",
    tags=["announcements"]
)


class AnnouncementIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    message: str = Field(..., min_length=1, max_length=2000)
    expiration_date: str  # ISO 8601 string (required)
    start_date: Optional[str] = None  # ISO 8601 string (optional)


def _require_teacher(teacher_username: Optional[str]) -> Dict[str, Any]:
    if not teacher_username:
        raise HTTPException(
            status_code=401, detail="Authentication required for this action")
    teacher = teachers_collection.find_one({"_id": teacher_username})
    if not teacher:
        raise HTTPException(
            status_code=401, detail="Invalid teacher credentials")
    return teacher


def _parse_iso(value: str, field: str) -> datetime:
    try:
        # Accept trailing Z by replacing with +00:00 for fromisoformat
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=400, detail=f"Invalid ISO 8601 date for '{field}'")


def _serialize(doc: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(doc)
    out["id"] = str(out.pop("_id"))
    return out


@router.get("", response_model=List[Dict[str, Any]])
@router.get("/", response_model=List[Dict[str, Any]])
def list_active_announcements() -> List[Dict[str, Any]]:
    """Public: list all currently active announcements (not expired, started)."""
    now_iso = datetime.now(timezone.utc).isoformat()
    cursor = announcements_collection.find({
        "expiration_date": {"$gte": now_iso},
        "$or": [
            {"start_date": {"$lte": now_iso}},
            {"start_date": None},
            {"start_date": {"$exists": False}},
        ],
    }).sort("created_at", -1)
    return [_serialize(doc) for doc in cursor]


@router.get("/all", response_model=List[Dict[str, Any]])
def list_all_announcements(
    teacher_username: Optional[str] = Query(None)
) -> List[Dict[str, Any]]:
    """Authenticated: list every announcement, including expired ones."""
    _require_teacher(teacher_username)
    cursor = announcements_collection.find({}).sort("created_at", -1)
    return [_serialize(doc) for doc in cursor]


@router.post("", response_model=Dict[str, Any])
def create_announcement(
    payload: AnnouncementIn,
    teacher_username: Optional[str] = Query(None),
) -> Dict[str, Any]:
    """Create a new announcement (auth required)."""
    teacher = _require_teacher(teacher_username)

    expiration_dt = _parse_iso(payload.expiration_date, "expiration_date")
    start_dt = None
    if payload.start_date:
        start_dt = _parse_iso(payload.start_date, "start_date")
        if start_dt >= expiration_dt:
            raise HTTPException(
                status_code=400,
                detail="start_date must be before expiration_date",
            )

    now = datetime.now(timezone.utc)
    doc = {
        "title": payload.title.strip(),
        "message": payload.message.strip(),
        "start_date": start_dt.isoformat() if start_dt else None,
        "expiration_date": expiration_dt.isoformat(),
        "created_at": now.isoformat(),
        "created_by": teacher["_id"],
    }
    result = announcements_collection.insert_one(doc)
    doc["_id"] = result.inserted_id
    return _serialize(doc)


def _to_object_id(announcement_id: str) -> ObjectId:
    try:
        return ObjectId(announcement_id)
    except (InvalidId, TypeError):
        raise HTTPException(status_code=400, detail="Invalid announcement id")


@router.put("/{announcement_id}", response_model=Dict[str, Any])
def update_announcement(
    announcement_id: str,
    payload: AnnouncementIn,
    teacher_username: Optional[str] = Query(None),
) -> Dict[str, Any]:
    """Update an existing announcement (auth required)."""
    _require_teacher(teacher_username)
    oid = _to_object_id(announcement_id)

    expiration_dt = _parse_iso(payload.expiration_date, "expiration_date")
    start_dt = None
    if payload.start_date:
        start_dt = _parse_iso(payload.start_date, "start_date")
        if start_dt >= expiration_dt:
            raise HTTPException(
                status_code=400,
                detail="start_date must be before expiration_date",
            )

    update = {
        "title": payload.title.strip(),
        "message": payload.message.strip(),
        "start_date": start_dt.isoformat() if start_dt else None,
        "expiration_date": expiration_dt.isoformat(),
    }
    result = announcements_collection.find_one_and_update(
        {"_id": oid},
        {"$set": update},
        return_document=True,
    )
    if not result:
        raise HTTPException(status_code=404, detail="Announcement not found")
    return _serialize(result)


@router.delete("/{announcement_id}")
def delete_announcement(
    announcement_id: str,
    teacher_username: Optional[str] = Query(None),
) -> Dict[str, str]:
    """Delete an announcement (auth required)."""
    _require_teacher(teacher_username)
    oid = _to_object_id(announcement_id)
    result = announcements_collection.delete_one({"_id": oid})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Announcement not found")
    return {"message": "Announcement deleted"}
