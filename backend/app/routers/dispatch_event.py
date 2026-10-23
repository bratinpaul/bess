import re
from datetime import date, datetime, time, timedelta
from typing import Literal, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app import models, schemas
from app.auth import tenant_scope as scope
from app.database import get_db
from app.schemas.dispatch_event import COMMAND_CODES, DISPATCH_STATUSES
from app.services.dispatch_event_import import (
    find_overlap,
    parse_dispatch_event_file,
    supersede_running,
    upsert_dispatch_events,
)

router = APIRouter(prefix="/api/dispatch-events", tags=["dispatch-events"])

Event = models.DispatchEvent


# ---------------------------------------------------------------- helpers


def _names(db: Session) -> dict[str, dict]:
    return {
        "ems": {e.ems_id: e.ems_code for e in db.query(models.EmsController)},
        "systems": {s.battery_system_id: s.system_name for s in db.query(models.BatterySystem)},
        "modes": {m.mode_code: m.description for m in db.query(models.EmsDispatchMode)},
        "services": {s.service_code: s.description for s in db.query(models.EmsGridService)},
    }


def _out(event: Event, names: dict[str, dict]) -> schemas.DispatchEventOut:
    duration = (event.effective_to - event.time).total_seconds() / 60 if event.effective_to else None
    return schemas.DispatchEventOut(
        dispatch_id=event.dispatch_id,
        effective_from=event.time,
        effective_to=event.effective_to,
        issued_at=event.issued_at,
        duration_min=round(duration, 1) if duration is not None else None,
        net_energy_kwh=event.import_kwh - event.export_kwh,
        issued_date=event.issued_at.date(),
        ems_id=event.ems_id,
        ems_code=names["ems"].get(event.ems_id),
        battery_system_id=event.battery_system_id,
        system_name=names["systems"].get(event.battery_system_id),
        command_code=event.command_code,
        dispatch_mode=event.dispatch_mode,
        dispatch_mode_description=names["modes"].get(event.dispatch_mode),
        grid_service=event.grid_service,
        grid_service_description=names["services"].get(event.grid_service),
        source=event.source,
        p_setpoint_kw=event.p_setpoint_kw,
        target_soc_pct=event.target_soc_pct,
        soc_start_pct=event.soc_start_pct,
        soc_end_pct=event.soc_end_pct,
        ramp_rate_kw_s=event.ramp_rate_kw_s,
        import_kwh=event.import_kwh,
        export_kwh=event.export_kwh,
        avg_price_mwh=event.avg_price_mwh,
        revenue_usd=event.revenue_usd,
        accepted=event.accepted,
        status=event.status,
        note=event.note,
        created_at=event.created_at,
        updated_at=event.updated_at,
    )


def _get(db: Session, dispatch_id: str) -> Event:
    event = db.query(Event).filter(Event.dispatch_id == dispatch_id).first()
    if not event:
        raise HTTPException(status_code=404, detail=f"Dispatch {dispatch_id} not found")
    return event


def _next_dispatch_id(db: Session) -> str:
    """DSP-00358 after DSP-00357 (numeric part of the highest DSP-nnnnn id)."""
    numbers = [int(m.group(1)) for (d,) in db.query(Event.dispatch_id) if (m := re.fullmatch(r"DSP-(\d+)", d))]
    return f"DSP-{(max(numbers) if numbers else 0) + 1:05d}"


def _close(db: Session, dispatch_id: str, start: datetime, end: datetime) -> None:
    """End a running dispatch that a newer one has replaced."""
    running = db.get(Event, (dispatch_id, start))
    if running is not None and running.effective_to is None:
        running.effective_to = end
        running.status = "Completed"


def _values(db: Session, payload: schemas.DispatchEventBase, dispatch_id: str) -> tuple[dict, Optional[tuple]]:
    """Validate references and the one-dispatch-at-a-time rule; turn the payload into column values.

    Also returns the running dispatch this one ends, as (dispatch_id, its start, new end), or None.
    """
    ems = db.get(models.EmsController, payload.ems_id)
    if not ems:
        raise HTTPException(status_code=400, detail="EMS controller not found")
    if not db.get(models.EmsDispatchMode, payload.dispatch_mode):
        raise HTTPException(status_code=400, detail=f"Unknown dispatch mode '{payload.dispatch_mode}'")
    if not db.get(models.EmsGridService, payload.grid_service):
        raise HTTPException(status_code=400, detail=f"Unknown grid service '{payload.grid_service}'")
    others = [
        (d, t, to) for d, t, to in db.query(Event.dispatch_id, Event.time, Event.effective_to)
        .filter(Event.ems_id == ems.ems_id, Event.dispatch_id != dispatch_id)
    ]
    # a newer dispatch ends the EMS's running one (closed at this one's start)
    others, closed = supersede_running(others, payload.effective_from)
    clash = find_overlap(others, payload.effective_from, payload.effective_to)
    if clash:
        if clash[2] is None:
            detail = (f"{ems.ems_code} is still running {clash[0]} (active since {clash[1]:%Y-%m-%d %H:%M}); "
                      f"set its end time first - one EMS runs one dispatch at a time")
        else:
            detail = (f"{ems.ems_code} already runs {clash[0]} from {clash[1]:%Y-%m-%d %H:%M} to {clash[2]:%Y-%m-%d %H:%M}; "
                      "one EMS runs one dispatch at a time")
        raise HTTPException(status_code=409, detail=detail)
    return dict(
        time=payload.effective_from,
        ems_id=ems.ems_id,
        battery_system_id=ems.battery_system_id,
        command_code=payload.command_code,
        dispatch_mode=payload.dispatch_mode,
        grid_service=payload.grid_service,
        source=payload.source,
        issued_at=payload.issued_at or payload.effective_from,
        effective_to=payload.effective_to,
        p_setpoint_kw=payload.p_setpoint_kw,
        target_soc_pct=payload.target_soc_pct,
        soc_start_pct=payload.soc_start_pct,
        soc_end_pct=payload.soc_end_pct,
        ramp_rate_kw_s=payload.ramp_rate_kw_s,
        import_kwh=payload.import_kwh,
        export_kwh=payload.export_kwh,
        avg_price_mwh=payload.avg_price_mwh,
        revenue_usd=payload.revenue_usd,
        accepted=payload.accepted,
        status=payload.status,
        note=payload.note,
    ), ((closed[0], closed[1], payload.effective_from) if closed else None)


class DispatchEventFilter:
    """Query-string filters for the list."""

    def __init__(
        self,
        request: Request,
        dispatch_mode: Optional[str] = None,
        grid_service: Optional[str] = None,
        command_code: Optional[str] = None,
        source: Optional[str] = None,
        status: Optional[Literal["Active", "Completed", "Aborted"]] = None,
        accepted: Optional[bool] = None,
        ems_id: Optional[int] = None,
        battery_system_id: Optional[int] = None,
        start: Optional[date] = None,
        end: Optional[date] = None,
        q: Optional[str] = None,
    ):
        self.dispatch_mode, self.grid_service, self.command_code, self.source = dispatch_mode, grid_service, command_code, source
        self.status, self.accepted, self.ems_id, self.battery_system_id = status, accepted, ems_id, battery_system_id
        self.start, self.end, self.q = start, end, q
        self.request = request

    def rows(self, db: Session) -> list[Event]:
        """Matching dispatches, newest first."""
        query = db.query(Event)
        allowed = scope.system_ids(db, self.request)  # a tenant-scoped caller: its tenant's systems only
        if allowed is not None:
            query = query.filter(Event.battery_system_id.in_(allowed))
        if self.dispatch_mode:
            query = query.filter(Event.dispatch_mode == self.dispatch_mode.upper())
        if self.grid_service:
            query = query.filter(Event.grid_service == self.grid_service.upper())
        if self.command_code:
            query = query.filter(Event.command_code == self.command_code.upper())
        if self.source:
            query = query.filter(Event.source == self.source)
        if self.status:
            query = query.filter(Event.status == self.status)
        if self.accepted is not None:
            query = query.filter(Event.accepted.is_(self.accepted))
        if self.ems_id is not None:
            query = query.filter(Event.ems_id == self.ems_id)
        if self.battery_system_id is not None:
            query = query.filter(Event.battery_system_id == self.battery_system_id)
        if self.start:
            query = query.filter(Event.time >= datetime.combine(self.start, time.min))
        if self.end:
            query = query.filter(Event.time < datetime.combine(self.end + timedelta(days=1), time.min))
        if self.q and self.q.strip():
            like = f"%{self.q.strip()}%"
            query = query.filter(or_(Event.dispatch_id.ilike(like), Event.dispatch_mode.ilike(like),
                                     Event.grid_service.ilike(like), Event.command_code.ilike(like),
                                     Event.source.ilike(like), Event.note.ilike(like)))
        return query.order_by(Event.time.desc(), Event.dispatch_id.desc()).all()


# ---------------------------------------------------------------- read


@router.get("", response_model=schemas.DispatchEventPage)
def list_dispatch_events(
    filters: DispatchEventFilter = Depends(),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """Dispatches, newest first, filtered; `stats` summarise the whole filtered set (not just the page)."""
    rows = filters.rows(db)
    names = _names(db)
    ended = [(e.effective_to - e.time).total_seconds() / 60 for e in rows if e.effective_to]
    stats = schemas.DispatchEventStats(
        total=len(rows),
        active=sum(1 for e in rows if e.status == "Active"),
        aborted=sum(1 for e in rows if e.status == "Aborted"),
        avg_duration_min=round(sum(ended) / len(ended), 1) if ended else None,
        import_mwh=round(float(sum(e.import_kwh for e in rows)) / 1000, 3),
        export_mwh=round(float(sum(e.export_kwh for e in rows)) / 1000, 3),
        revenue_usd=round(float(sum(e.revenue_usd or 0 for e in rows)), 2),
        by_mode={m: sum(1 for e in rows if e.dispatch_mode == m) for m in names["modes"]},
        by_service={s: sum(1 for e in rows if e.grid_service == s) for s in names["services"]},
    )
    first = (page - 1) * page_size
    return schemas.DispatchEventPage(
        items=[_out(e, names) for e in rows[first : first + page_size]],
        total=len(rows),
        page=page,
        page_size=page_size,
        stats=stats,
    )


def _pieces(start: datetime, end: datetime):
    """Split [start, end) at each whole hour: yields (piece start, minutes)."""
    t = start
    while t < end:
        nxt = min(end, t.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1))
        yield t, (nxt - t).total_seconds() / 60
        t = nxt


@router.get("/analytics", response_model=schemas.DispatchEventAnalytics)
def dispatch_event_analytics(filters: DispatchEventFilter = Depends(), db: Session = Depends(get_db)):
    """Aggregates for the graphical tab, over the same filtered set as the list."""
    rows = sorted(filters.rows(db), key=lambda e: (e.time, e.dispatch_id))
    names = _names(db)
    modes = list(names["modes"])

    def f(value) -> float:
        return float(value or 0)

    def mean(values: list[float]) -> Optional[float]:
        return round(sum(values) / len(values), 1) if values else None

    # per issued day: events, revenue and energy (the workbook's Daily table)
    days: dict[date, dict] = {}

    def day(d: date) -> dict:
        return days.setdefault(d, dict(events=0, events_by_mode={}, revenue_usd=0.0, import_kwh=0.0, export_kwh=0.0,
                                       minutes_by_mode={}))

    hours = [dict(import_kwh=0.0, export_kwh=0.0, price_minutes=0.0, priced_minutes=0.0) for _ in range(24)]
    per_mode = {m: dict(events=0, minutes=0.0, import_kwh=0.0, export_kwh=0.0, revenue_usd=0.0, durations=[]) for m in modes}

    for e in rows:
        d = day(e.issued_at.date())
        d["events"] += 1
        d["events_by_mode"][e.dispatch_mode] = d["events_by_mode"].get(e.dispatch_mode, 0) + 1
        d["revenue_usd"] += f(e.revenue_usd)
        d["import_kwh"] += f(e.import_kwh)
        d["export_kwh"] += f(e.export_kwh)
        m = per_mode.setdefault(e.dispatch_mode, dict(events=0, minutes=0.0, import_kwh=0.0, export_kwh=0.0,
                                                      revenue_usd=0.0, durations=[]))
        m["events"] += 1
        m["import_kwh"] += f(e.import_kwh)
        m["export_kwh"] += f(e.export_kwh)
        m["revenue_usd"] += f(e.revenue_usd)
        if e.effective_to is None:
            continue
        total_min = (e.effective_to - e.time).total_seconds() / 60
        m["durations"].append(total_min)
        m["minutes"] += total_min
        # spread time and energy over the hours (and days) the dispatch actually ran
        for t, minutes in _pieces(e.time, e.effective_to):
            share = minutes / total_min if total_min else 0
            h = hours[t.hour]
            h["import_kwh"] += f(e.import_kwh) * share
            h["export_kwh"] += f(e.export_kwh) * share
            if e.avg_price_mwh is not None:
                h["price_minutes"] += float(e.avg_price_mwh) * minutes
                h["priced_minutes"] += minutes
            by_mode = day(t.date())["minutes_by_mode"]
            by_mode[e.dispatch_mode] = by_mode.get(e.dispatch_mode, 0) + minutes

    ordered_days = []
    if days:
        # time that spills past a filtered date range (e.g. standby running past midnight) stays out of the chart
        first, last = max(min(days), filters.start or min(days)), min(max(days), filters.end or max(days))
        if (last - first).days <= 366:
            for i in range((last - first).days + 1):
                d = first + timedelta(days=i)
                v = days.get(d) or day(d)
                ordered_days.append(schemas.DispatchDay(
                    date=d, events=v["events"], events_by_mode=v["events_by_mode"], revenue_usd=round(v["revenue_usd"], 2),
                    import_kwh=round(v["import_kwh"], 1), export_kwh=round(v["export_kwh"], 1),
                    minutes_by_mode={k: round(x, 1) for k, x in v["minutes_by_mode"].items()}))

    sources: dict[str, int] = {}
    for e in rows:
        key = e.source or "Unspecified"
        sources[key] = sources.get(key, 0) + 1

    return schemas.DispatchEventAnalytics(
        total=len(rows),
        open_dispatches=sum(1 for e in rows if e.effective_to is None),
        modes=[
            schemas.DispatchModeSummary(
                mode=k, description=names["modes"].get(k), events=v["events"], minutes=round(v["minutes"], 1),
                import_kwh=round(v["import_kwh"], 1), export_kwh=round(v["export_kwh"], 1),
                revenue_usd=round(v["revenue_usd"], 2), mean_duration_min=mean(v["durations"]),
                max_duration_min=round(max(v["durations"]), 1) if v["durations"] else None)
            for k, v in per_mode.items()
        ],
        days=ordered_days,
        hours=[
            schemas.DispatchHour(
                hour=i, import_kwh=round(h["import_kwh"], 1), export_kwh=round(h["export_kwh"], 1),
                avg_price_mwh=round(h["price_minutes"] / h["priced_minutes"], 2) if h["priced_minutes"] else None)
            for i, h in enumerate(hours)
        ],
        sources=[schemas.DispatchCount(key=k, count=n) for k, n in sorted(sources.items(), key=lambda kv: (-kv[1], kv[0]))],
        dispatches=[
            schemas.DispatchPoint(
                dispatch_id=e.dispatch_id, effective_from=e.time, effective_to=e.effective_to, dispatch_mode=e.dispatch_mode,
                p_setpoint_kw=f(e.p_setpoint_kw),
                soc_start_pct=float(e.soc_start_pct) if e.soc_start_pct is not None else None,
                soc_end_pct=float(e.soc_end_pct) if e.soc_end_pct is not None else None,
                target_soc_pct=float(e.target_soc_pct) if e.target_soc_pct is not None else None,
                avg_price_mwh=float(e.avg_price_mwh) if e.avg_price_mwh is not None else None,
                revenue_usd=float(e.revenue_usd) if e.revenue_usd is not None else None,
                duration_min=round((e.effective_to - e.time).total_seconds() / 60, 1) if e.effective_to else None)
            for e in rows
        ],
    )


@router.get("/lookups", response_model=schemas.DispatchEventLookups)
def get_lookups(db: Session = Depends(get_db)):
    """EMS controllers, dispatch modes, grid services and the other choices for the form and filters."""
    systems = {s.battery_system_id: s.system_name for s in db.query(models.BatterySystem)}
    sources = sorted({s for (s,) in db.query(Event.source).distinct() if s})
    return schemas.DispatchEventLookups(
        ems=[schemas.DispatchEmsOption(ems_id=e.ems_id, ems_code=e.ems_code, battery_system_id=e.battery_system_id,
                                       system_name=systems.get(e.battery_system_id))
             for e in db.query(models.EmsController).order_by(models.EmsController.ems_code)],
        modes=[schemas.DispatchCodeOption(code=m.mode_code, description=m.description)
               for m in db.query(models.EmsDispatchMode).order_by(models.EmsDispatchMode.mode_code)],
        services=[schemas.DispatchCodeOption(code=s.service_code, description=s.description)
                  for s in db.query(models.EmsGridService).order_by(models.EmsGridService.service_code)],
        command_codes=list(COMMAND_CODES),
        statuses=list(DISPATCH_STATUSES),
        sources=sources,
    )


@router.get("/next-id")
def next_dispatch_id(db: Session = Depends(get_db)):
    return {"dispatch_id": _next_dispatch_id(db)}


@router.post("/bulk", response_model=schemas.BulkDispatchEventResult)
async def bulk_load_dispatch_events(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Load an .xlsx ('Dispatch Events' sheet) or .csv dispatch log.

    Existing (dispatch_id, effective_from) rows are updated in the columns the file has; the others keep their values.
    """
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    sheet, valid, errors, total, ignored, update_cols, closes = parse_dispatch_event_file(
        file.filename or "upload", content, db)
    # running dispatches that a newer one in the file replaces are ended at its start
    for closed_id, (start, end) in closes.items():
        _close(db, closed_id, start, end)
    # existing dispatches are updated only in the columns the file has
    inserted, updated = upsert_dispatch_events(db, valid, update_cols)
    db.commit()
    return schemas.BulkDispatchEventResult(
        filename=file.filename or "upload",
        sheet=sheet,
        total_rows=total,
        valid_rows=len(valid),
        inserted=inserted,
        updated=updated,
        error_count=len(errors),
        errors=errors[:200],
        ignored_columns=ignored,
        closed_dispatches=[f"{d} ended at {end:%Y-%m-%d %H:%M}" for d, (_, end) in sorted(closes.items())],
    )


@router.get("/{dispatch_id}", response_model=schemas.DispatchEventOut)
def get_dispatch_event(dispatch_id: str, db: Session = Depends(get_db)):
    return _out(_get(db, dispatch_id), _names(db))


# ---------------------------------------------------------------- write


@router.post("", response_model=schemas.DispatchEventOut, status_code=201)
def create_dispatch_event(payload: schemas.DispatchEventCreate, db: Session = Depends(get_db)):
    dispatch_id = payload.dispatch_id or _next_dispatch_id(db)
    if db.query(Event).filter(Event.dispatch_id == dispatch_id).first():
        raise HTTPException(status_code=409, detail=f"Dispatch {dispatch_id} already exists")
    values, closed = _values(db, payload, dispatch_id)
    if closed:
        _close(db, *closed)
    db.add(Event(dispatch_id=dispatch_id, **values))
    db.commit()
    return get_dispatch_event(dispatch_id, db)


@router.put("/{dispatch_id}", response_model=schemas.DispatchEventOut)
def update_dispatch_event(dispatch_id: str, payload: schemas.DispatchEventUpdate, db: Session = Depends(get_db)):
    event = _get(db, dispatch_id)
    values, closed = _values(db, payload, dispatch_id)
    if closed:
        _close(db, *closed)
    if values["time"] != event.time:
        # effective_from is part of the key (and the hypertable's partition column): replace the row
        created = event.created_at
        db.delete(event)
        db.flush()
        db.add(Event(dispatch_id=dispatch_id, created_at=created, **values))
    else:
        for field, value in values.items():
            setattr(event, field, value)
    db.commit()
    return get_dispatch_event(dispatch_id, db)


@router.delete("/{dispatch_id}", status_code=204)
def delete_dispatch_event(dispatch_id: str, db: Session = Depends(get_db)):
    db.delete(_get(db, dispatch_id))
    db.commit()
    return None
