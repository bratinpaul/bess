"""Reference calendar (battery_master.calendar_day): list / filter, read, add, edit, delete and bulk load.
Day of week, weekend and day type are derived from the date and the holiday flag."""
from datetime import date
from typing import Literal, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.services.calendar_import import CalendarImportError, parse_calendar_file, upsert_calendar_rows

router = APIRouter(prefix="/api/calendar-days", tags=["calendar"])

Day = models.CalendarDay


def _get(db: Session, d: date) -> Day:
    row = db.get(Day, d)
    if not row:
        raise HTTPException(status_code=404, detail=f"{d.isoformat()} is not in the calendar")
    return row


def _bad(exc: ValueError):
    raise HTTPException(status_code=422, detail=str(exc))


@router.get("", response_model=schemas.CalendarDayPage)
def list_days(start: Optional[date] = None, end: Optional[date] = None,
              day_type: Optional[Literal["Weekday", "Weekend", "Holiday"]] = None, holidays_only: bool = False,
              order: Literal["asc", "desc"] = "asc", page: int = Query(1, ge=1),
              page_size: int = Query(50, ge=1, le=1000), db: Session = Depends(get_db)):
    """Calendar days in a date range, with the day-type counts and coverage of that range."""
    q = db.query(Day)
    if start:
        q = q.filter(Day.calendar_date >= start)
    if end:
        q = q.filter(Day.calendar_date <= end)
    counts = {t: n for t, n in q.with_entities(Day.day_type, func.count()).group_by(Day.day_type)}
    first, last = q.with_entities(func.min(Day.calendar_date), func.max(Day.calendar_date)).one()
    in_range = sum(counts.values())
    missing = ((last - first).days + 1 - in_range) if first else 0
    if day_type:
        q = q.filter(Day.day_type == day_type)
    if holidays_only:
        q = q.filter(Day.is_holiday.is_(True))
    total = q.count()
    col = Day.calendar_date.asc() if order == "asc" else Day.calendar_date.desc()
    items = q.order_by(col).offset((page - 1) * page_size).limit(page_size).all()
    return schemas.CalendarDayPage(items=items, total=total, page=page, page_size=page_size, counts=counts,
                                   first_date=first, last_date=last, missing_days=missing)


@router.get("/{calendar_date}", response_model=schemas.CalendarDayOut)
def get_day(calendar_date: date, db: Session = Depends(get_db)):
    return _get(db, calendar_date)


@router.post("", response_model=schemas.CalendarDayOut, status_code=201)
def add_day(payload: schemas.CalendarDayCreate, db: Session = Depends(get_db)):
    """Add a day; a date already in the calendar is refused (edit it instead)."""
    if db.get(Day, payload.calendar_date):
        raise HTTPException(status_code=409, detail=f"{payload.calendar_date.isoformat()} is already in the calendar")
    row = Day(**payload.complete(payload.calendar_date))
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.put("/{calendar_date}", response_model=schemas.CalendarDayOut)
def update_day(calendar_date: date, payload: schemas.CalendarDayUpdate, db: Session = Depends(get_db)):
    row = _get(db, calendar_date)
    try:
        values = payload.complete(calendar_date)
    except ValueError as exc:
        _bad(exc)
    for field, value in values.items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/{calendar_date}", status_code=204)
def delete_day(calendar_date: date, db: Session = Depends(get_db)):
    db.delete(_get(db, calendar_date))
    db.commit()
    return None


@router.post("/bulk", response_model=schemas.BulkCalendarResult)
async def bulk_load(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Load a .csv / .xlsx calendar; existing dates are updated."""
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    try:
        valid, errors, total, ignored = parse_calendar_file(file.filename or "upload", content)
    except CalendarImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    inserted, updated = upsert_calendar_rows(db, valid)
    db.commit()
    n_errors = len(errors)
    if ignored:
        errors.insert(0, schemas.BulkCalendarRowError(row=1, errors=[f"Ignored unknown column(s): {', '.join(ignored)}"]))
    return schemas.BulkCalendarResult(
        filename=file.filename or "upload", total_rows=total, valid_rows=len(valid), inserted=inserted, updated=updated,
        error_count=n_errors, errors=errors[:200], first_date=valid[0]["calendar_date"] if valid else None,
        last_date=valid[-1]["calendar_date"] if valid else None, holidays=sum(1 for r in valid if r["is_holiday"]))
