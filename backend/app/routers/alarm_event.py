import re
from datetime import date, datetime, time, timedelta
from typing import Literal, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app import models, schemas
from app.auth import tenant_scope as scope
from app.database import get_db
from app.models.alarm_catalog import ALARM_SOURCES
from app.services.alarm_event_import import AlarmEventImportError, parse_alarm_event_file, upsert_alarm_events
from app.services.asset_matcher import LABELS, AssetMatcher

router = APIRouter(prefix="/api/alarm-events", tags=["alarm-events"])

Event = models.AlarmEvent
Catalog = models.AlarmCatalog


# ---------------------------------------------------------------- helpers


def _names(db: Session) -> tuple[dict, dict, dict]:
    severities = {s.severity_level: s.severity_name for s in db.query(models.AlarmSeverity)}
    systems = {s.battery_system_id: s.system_name for s in db.query(models.BatterySystem)}
    assets = {(c.asset_type, c.asset_id): c.name for cs in AssetMatcher(db).candidates.values() for c in cs}
    return severities, systems, assets


def _out(event: Event, entry: Catalog, names: tuple[dict, dict, dict]) -> schemas.AlarmEventOut:
    severities, systems, assets = names
    duration = (event.end_time - event.time).total_seconds() / 60 if event.end_time else None
    return schemas.AlarmEventOut(
        alarm_id=event.alarm_id,
        start_time=event.time,
        end_time=event.end_time,
        status="Active" if event.end_time is None else "Cleared",
        duration_min=round(duration, 1) if duration is not None else None,
        start_date=event.time.date(),
        alarm_catalog_id=entry.alarm_catalog_id,
        source=entry.source,
        alarm_code=entry.alarm_code,
        alarm_type=entry.alarm_type,
        description=entry.description,
        probable_cause=entry.probable_cause,
        severity_level=event.severity_level,
        severity_name=severities.get(event.severity_level),
        asset_type=event.asset_type,
        asset_code=event.asset_code,
        linked_asset_type=event.linked_asset_type,
        linked_asset_id=event.linked_asset_id,
        linked_asset_name=assets.get((event.linked_asset_type, event.linked_asset_id)),
        asset_match=event.asset_match,
        battery_system_id=event.battery_system_id,
        system_name=systems.get(event.battery_system_id),
        trigger_value=event.trigger_value,
        threshold_value=event.threshold_value,
        unit=event.unit,
        acknowledged_by=event.acknowledged_by,
        acknowledged_at=event.acknowledged_at,
        created_at=event.created_at,
        updated_at=event.updated_at,
    )


def _get(db: Session, alarm_id: str) -> tuple[Event, Catalog]:
    row = (
        db.query(Event, Catalog)
        .join(Catalog, Catalog.alarm_catalog_id == Event.alarm_catalog_id)
        .filter(Event.alarm_id == alarm_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail=f"Alarm {alarm_id} not found")
    return row


def _next_alarm_id(db: Session) -> str:
    """ALM-00073 after ALM-00072 (numeric part of the highest ALM-nnnnn id)."""
    numbers = [int(m.group(1)) for (a,) in db.query(Event.alarm_id) if (m := re.fullmatch(r"ALM-(\d+)", a))]
    return f"ALM-{(max(numbers) if numbers else 0) + 1:05d}"


def _values(db: Session, payload: schemas.AlarmEventBase) -> dict:
    """Validate references and turn the payload into column values."""
    entry = db.get(Catalog, payload.alarm_catalog_id)
    if not entry:
        raise HTTPException(status_code=400, detail="Alarm catalog entry not found")
    system_id = None
    asset_type, asset_code = payload.asset_type, payload.asset_code
    if payload.linked_asset_type:
        asset = AssetMatcher(db).get(payload.linked_asset_type, payload.linked_asset_id)
        if not asset:
            raise HTTPException(status_code=400, detail=f"{LABELS[payload.linked_asset_type]} {payload.linked_asset_id} not found")
        system_id = asset.battery_system_id
        # a linked asset is always shown under its master-data type and name
        asset_type = LABELS[payload.linked_asset_type]
        asset_code = asset.name
    return dict(
        time=payload.start_time,
        end_time=payload.end_time,
        alarm_catalog_id=entry.alarm_catalog_id,
        severity_level=payload.severity_level if payload.severity_level is not None else entry.severity_level,
        asset_type=asset_type,
        asset_code=asset_code,
        linked_asset_type=payload.linked_asset_type,
        linked_asset_id=payload.linked_asset_id,
        asset_match="manual" if payload.linked_asset_type else None,
        battery_system_id=system_id,
        trigger_value=payload.trigger_value,
        threshold_value=payload.threshold_value,
        unit=payload.unit,
        acknowledged_by=payload.acknowledged_by,
        acknowledged_at=payload.acknowledged_at,
    )


# ---------------------------------------------------------------- read


class AlarmEventFilter:
    """Query-string filters shared by the list and the analytics endpoints."""

    def __init__(
        self,
        request: Request,
        source: Optional[str] = None,
        severity_level: Optional[int] = Query(None, ge=0, le=3),
        status: Optional[Literal["active", "cleared"]] = None,
        acknowledged: Optional[bool] = None,
        battery_system_id: Optional[int] = None,
        alarm_catalog_id: Optional[int] = None,
        start: Optional[date] = None,
        end: Optional[date] = None,
        q: Optional[str] = None,
    ):
        self.source, self.severity_level, self.status, self.acknowledged = source, severity_level, status, acknowledged
        self.battery_system_id, self.alarm_catalog_id, self.start, self.end, self.q = (
            battery_system_id, alarm_catalog_id, start, end, q)
        self.request = request

    def rows(self, db: Session) -> list[tuple[Event, Catalog]]:
        """Matching alarms with their catalog entries, newest first (a tenant-scoped caller: its tenant's systems only)."""
        query = db.query(Event, Catalog).join(Catalog, Catalog.alarm_catalog_id == Event.alarm_catalog_id)
        allowed = scope.system_ids(db, self.request)
        if allowed is not None:
            query = query.filter(Event.battery_system_id.in_(allowed))
        if self.source:
            query = query.filter(Catalog.source == self.source.upper())
        if self.severity_level is not None:
            query = query.filter(Event.severity_level == self.severity_level)
        if self.status == "active":
            query = query.filter(Event.end_time.is_(None))
        elif self.status == "cleared":
            query = query.filter(Event.end_time.isnot(None))
        if self.acknowledged is not None:
            query = query.filter(Event.acknowledged_at.isnot(None) if self.acknowledged else Event.acknowledged_at.is_(None))
        if self.battery_system_id is not None:
            query = query.filter(Event.battery_system_id == self.battery_system_id)
        if self.alarm_catalog_id is not None:
            query = query.filter(Event.alarm_catalog_id == self.alarm_catalog_id)
        if self.start:
            query = query.filter(Event.time >= datetime.combine(self.start, time.min))
        if self.end:
            query = query.filter(Event.time < datetime.combine(self.end + timedelta(days=1), time.min))
        if self.q and self.q.strip():
            like = f"%{self.q.strip()}%"
            query = query.filter(or_(Event.alarm_id.ilike(like), Catalog.alarm_code.ilike(like), Catalog.description.ilike(like),
                                     Event.asset_code.ilike(like), Catalog.alarm_type.ilike(like), Event.acknowledged_by.ilike(like)))
        return query.order_by(Event.time.desc(), Event.alarm_id.desc()).all()


@router.get("", response_model=schemas.AlarmEventPage)
def list_alarm_events(
    filters: AlarmEventFilter = Depends(),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """Alarms, newest first, filtered; `stats` summarise the whole filtered set (not just the page)."""
    rows = filters.rows(db)
    names = _names(db)
    severities = names[0]
    cleared = [(e.end_time - e.time).total_seconds() / 60 for e, _ in rows if e.end_time]
    stats = schemas.AlarmEventStats(
        total=len(rows),
        active=sum(1 for e, _ in rows if e.end_time is None),
        acknowledged=sum(1 for e, _ in rows if e.acknowledged_at is not None),
        critical=sum(1 for e, _ in rows if e.severity_level == 3),
        mean_minutes_to_clear=round(sum(cleared) / len(cleared), 1) if cleared else None,
        by_source={s: sum(1 for _, c in rows if c.source == s) for s in ALARM_SOURCES},
        by_severity={name: sum(1 for e, _ in rows if e.severity_level == lvl) for lvl, name in sorted(severities.items())},
    )
    first = (page - 1) * page_size
    return schemas.AlarmEventPage(
        items=[_out(e, c, names) for e, c in rows[first : first + page_size]],
        total=len(rows),
        page=page,
        page_size=page_size,
        stats=stats,
    )


@router.get("/analytics", response_model=schemas.AlarmEventAnalytics)
def alarm_event_analytics(filters: AlarmEventFilter = Depends(), db: Session = Depends(get_db)):
    """Aggregates for the graphical tab, over the same filtered set as the list."""
    rows = filters.rows(db)
    severities, _, assets = _names(db)
    levels = sorted(severities)

    def minutes(a: datetime, b: datetime) -> float:
        return (b - a).total_seconds() / 60

    def mean(values: list[float]) -> Optional[float]:
        return round(sum(values) / len(values), 1) if values else None

    by_severity = []
    for lvl in levels:
        group = [e for e, _ in rows if e.severity_level == lvl]
        acked = [e for e in group if e.acknowledged_at is not None]
        by_severity.append(schemas.AlarmSeverityCount(
            severity_level=lvl, severity_name=severities[lvl], count=len(group), acknowledged=len(acked),
            mean_minutes_to_ack=mean([minutes(e.time, e.acknowledged_at) for e in acked])))

    types: dict[str, int] = {}
    for _, c in rows:
        key = c.alarm_type or "Unspecified"
        types[key] = types.get(key, 0) + 1

    # one entry per calendar day from the first to the last alarm (or the filter's dates), zero days included
    daily: list[schemas.AlarmDailyCount] = []
    if rows:
        days = [e.time.date() for e, _ in rows]
        first, last = filters.start or min(days), filters.end or max(days)
        if first <= last and (last - first).days <= 366:
            counts: dict[date, list[int]] = {}
            for e, _ in rows:
                counts.setdefault(e.time.date(), [0] * len(levels))[levels.index(e.severity_level)] += 1
            for i in range((last - first).days + 1):
                day = first + timedelta(days=i)
                daily.append(schemas.AlarmDailyCount(date=day, by_severity=counts.get(day, [0] * len(levels))))

    hours = [0] * 24
    for e, _ in rows:
        hours[e.time.hour] += 1

    # (source, code) -> [description, count, durations of cleared occurrences]
    codes: dict[tuple[str, str], list] = {}
    for e, c in rows:
        entry = codes.setdefault((c.source, c.alarm_code), [c.description, 0, []])
        entry[1] += 1
        if e.end_time:
            entry[2].append(minutes(e.time, e.end_time))
    top_codes = [
        schemas.AlarmCodeCount(source=src, alarm_code=code, description=desc, count=n,
                               share_pct=round(100 * n / len(rows), 1), mean_duration_min=mean(durations))
        for (src, code), (desc, n, durations) in sorted(codes.items(), key=lambda kv: (-kv[1][1], kv[0]))[:10]
    ]

    # (asset type, master-data name) -> [source, count]
    asset_counts: dict[tuple, list] = {}
    for e, c in rows:
        name = assets.get((e.linked_asset_type, e.linked_asset_id)) or e.asset_code or "Unknown asset"
        asset_counts.setdefault((e.asset_type, name), [c.source, 0])[1] += 1
    top_assets = [
        schemas.AlarmAssetCount(asset_type=kind, asset_name=name, source=src, count=n)
        for (kind, name), (src, n) in sorted(asset_counts.items(), key=lambda kv: (-kv[1][1], kv[0][1]))[:10]
    ]

    duration_by_source = []
    for src in ALARM_SOURCES:
        durations = [minutes(e.time, e.end_time) for e, c in rows if c.source == src and e.end_time]
        duration_by_source.append(schemas.AlarmSourceDuration(
            source=src, cleared=len(durations), mean_duration_min=mean(durations),
            max_duration_min=round(max(durations), 1) if durations else None))

    return schemas.AlarmEventAnalytics(
        total=len(rows),
        by_source=[schemas.AlarmCount(key=s, count=sum(1 for _, c in rows if c.source == s)) for s in ALARM_SOURCES],
        by_severity=by_severity,
        by_type=[schemas.AlarmCount(key=k, count=n) for k, n in sorted(types.items(), key=lambda kv: (-kv[1], kv[0]))],
        daily=daily,
        hour_of_day=hours,
        top_codes=top_codes,
        top_assets=top_assets,
        duration_by_source=duration_by_source,
        durations=[
            schemas.AlarmDurationPoint(alarm_id=e.alarm_id, start_time=e.time, duration_min=round(minutes(e.time, e.end_time), 1),
                                       severity_level=e.severity_level, source=c.source, alarm_code=c.alarm_code)
            for e, c in reversed(rows) if e.end_time
        ],
    )


@router.get("/lookups", response_model=schemas.AlarmEventLookups)
def get_lookups(db: Session = Depends(get_db)):
    """Catalog entries, assets (per master-data type), severities and battery systems for the form and filters."""
    matcher = AssetMatcher(db)
    return schemas.AlarmEventLookups(
        catalog=[
            schemas.AlarmEventCatalogOption.model_validate(c, from_attributes=True)
            for c in db.query(Catalog).order_by(Catalog.source, Catalog.alarm_code)
        ],
        assets=[
            schemas.AlarmEventAssetOption(asset_type=c.asset_type, asset_id=c.asset_id, name=c.name,
                                          battery_system_id=c.battery_system_id)
            for cs in matcher.candidates.values() for c in cs
        ],
        severities=[{"severity_level": s.severity_level, "severity_name": s.severity_name}
                    for s in db.query(models.AlarmSeverity).order_by(models.AlarmSeverity.severity_level)],
        systems=[{"battery_system_id": s.battery_system_id, "system_name": s.system_name}
                 for s in db.query(models.BatterySystem).order_by(models.BatterySystem.system_name)],
    )


@router.get("/next-id")
def next_alarm_id(db: Session = Depends(get_db)):
    return {"alarm_id": _next_alarm_id(db)}


@router.post("/bulk", response_model=schemas.BulkAlarmEventResult)
async def bulk_load_alarm_events(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Load an .xlsx ('Alarms' sheet) or .csv alarm log.

    Existing (alarm_id, start time) rows are updated in the columns the file has; the others keep their values.
    """
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    try:
        sheet, valid, errors, total, ignored, linked, update_cols = parse_alarm_event_file(file.filename or "upload", content, db)
    except AlarmEventImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    # existing alarms are updated only in the columns the file has
    inserted, updated = upsert_alarm_events(db, valid, update_cols)
    db.commit()
    return schemas.BulkAlarmEventResult(
        filename=file.filename or "upload",
        sheet=sheet,
        total_rows=total,
        valid_rows=len(valid),
        inserted=inserted,
        updated=updated,
        error_count=len(errors),
        errors=errors[:200],
        assets_linked=linked,
        ignored_columns=ignored,
    )


@router.get("/{alarm_id}", response_model=schemas.AlarmEventOut)
def get_alarm_event(alarm_id: str, db: Session = Depends(get_db)):
    event, entry = _get(db, alarm_id)
    return _out(event, entry, _names(db))


# ---------------------------------------------------------------- write


@router.post("", response_model=schemas.AlarmEventOut, status_code=201)
def create_alarm_event(payload: schemas.AlarmEventCreate, db: Session = Depends(get_db)):
    alarm_id = payload.alarm_id or _next_alarm_id(db)
    if db.query(Event).filter(Event.alarm_id == alarm_id).first():
        raise HTTPException(status_code=409, detail=f"Alarm {alarm_id} already exists")
    db.add(Event(alarm_id=alarm_id, **_values(db, payload)))
    db.commit()
    return get_alarm_event(alarm_id, db)


@router.put("/{alarm_id}", response_model=schemas.AlarmEventOut)
def update_alarm_event(alarm_id: str, payload: schemas.AlarmEventUpdate, db: Session = Depends(get_db)):
    event, _ = _get(db, alarm_id)
    values = _values(db, payload)
    if values["time"] != event.time:
        # the start time is part of the key (and the hypertable's partition column): replace the row
        created = event.created_at
        db.delete(event)
        db.flush()
        db.add(Event(alarm_id=alarm_id, created_at=created, **values))
    else:
        for field, value in values.items():
            setattr(event, field, value)
    db.commit()
    return get_alarm_event(alarm_id, db)


@router.delete("/{alarm_id}", status_code=204)
def delete_alarm_event(alarm_id: str, db: Session = Depends(get_db)):
    event, _ = _get(db, alarm_id)
    db.delete(event)
    db.commit()
    return None
