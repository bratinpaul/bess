"""Batch API: the realtime snapshot batch and the snapshot simulator.

Only the HTTP layer lives here. The code is in the project root, next to the backend:
  * <project>/snapshot_loader    - realtime batch, its control (batch_control.py) and the snapshot loader
  * <project>/snapshot_simulator - the snapshot simulator
  * <project>/static_data_loader - the static master data batch and its control (static_control.py)
  * <project>/historical_loader  - the generic historical telemetry loader and its control (historical_control.py)
  * <project>/historical_generator - historical file generation per site and its control (generator_control.py)
"""
import sys
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app import schemas
from app.database import SessionLocal, get_db

PROJECT = Path(__file__).resolve().parents[3]
for folder in (PROJECT, PROJECT / "snapshot_loader", PROJECT / "static_data_loader", PROJECT / "historical_loader",
               PROJECT / "historical_generator"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))
import batch_control  # noqa: E402  (snapshot_loader/batch_control.py)
from snapshot_simulator import simulator as snapshot_simulator  # noqa: E402
import static_control  # noqa: E402  (static_data_loader/static_control.py)
import historical_control  # noqa: E402  (historical_loader/historical_control.py)
import generator_control  # noqa: E402  (historical_generator/generator_control.py)

# ---------------------------------------------------------------- realtime batch (code: <project>/snapshot_loader)

router = APIRouter(prefix="/api/batch/realtime", tags=["batch"])


@router.get("/status", response_model=schemas.BatchStatus)
def batch_status(db: Session = Depends(get_db)):
    """What's waiting in the inbox, whether a run is going, the schedule, and the last logged run."""
    running, since = batch_control.lock_state()
    last = batch_control.last_log(db)
    return schemas.BatchStatus(
        inbox=str(batch_control.INBOX), archive=str(batch_control.ARCHIVE),
        files=[schemas.InboxFile(**f) for f in batch_control.inbox_files()],
        running=running, running_since=since, schedule=schemas.ScheduleInfo(**batch_control.schedule_info()),
        last_run=schemas.BatchLogOut.model_validate(last) if last else None,
    )


@router.post("/run", response_model=schemas.BatchRunResult)
def run_batch(db: Session = Depends(get_db)):
    """Run the batch now (same as a scheduled run) and return what it loaded.

    A plain (threaded) endpoint on purpose: the batch calls this backend's bulk-load APIs while it runs.
    """
    result = batch_control.run_now()
    runs = batch_control.logs_since(db, result["started_at"])
    return schemas.BatchRunResult(**result, runs=[schemas.BatchLogOut.model_validate(r) for r in runs])


@router.get("/logs", response_model=schemas.BatchLogPage)
def list_logs(
    status: Optional[Literal["SUCCESS", "PARTIAL", "FAILED"]] = None,
    q: Optional[str] = None,
    limit: int = Query(25, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """battery_raw.batchlog rows, newest first."""
    items, total, counts = batch_control.list_logs(db, status, q, limit, offset)
    return schemas.BatchLogPage(items=[schemas.BatchLogOut.model_validate(r) for r in items], total=total, counts=counts)


@router.get("/logs/{batch_id}", response_model=schemas.BatchLogDetail)
def get_log(batch_id: int, db: Session = Depends(get_db)):
    row = batch_control.get_log(db, batch_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"Batch log #{batch_id} not found")
    return schemas.BatchLogDetail.model_validate(row)


# ---------------------------------------------------------------- snapshot simulator (code: <project>/snapshot_simulator)

simulator = APIRouter(prefix="/api/batch/simulator", tags=["batch"])


@simulator.get("/info", response_model=schemas.SimulatorInfo)
def simulator_info(db: Session = Depends(get_db)):
    """The historical days the simulator samples from, and where it writes."""
    return schemas.SimulatorInfo(**snapshot_simulator.source_info(db))


@simulator.post("/run", response_model=schemas.SimulatorResult)
def run_simulator(payload: schemas.SimulatorRequest, db: Session = Depends(get_db)):
    """Write one snapshot file per 5 minutes from start to end into the realtime inbox (sampled from stored telemetry)."""
    result = snapshot_simulator.simulate(
        db, payload.start, payload.end, seed=payload.seed, overwrite=payload.overwrite,
        source_from=payload.source_from, source_to=payload.source_to,
    )
    return schemas.SimulatorResult(**vars(result))


# ---------------------------------------------------------------- static master data batch (code: <project>/static_data_loader)

static = APIRouter(prefix="/api/batch/static", tags=["batch"])


@static.get("/status", response_model=schemas.StaticBatchStatus)
def static_status(db: Session = Depends(get_db)):
    """JSON files waiting in input/static, whether a run is going, and the last logged run."""
    running, since = static_control.lock_state()
    last = static_control.last_log(db)
    return schemas.StaticBatchStatus(
        inbox=str(static_control.INBOX), archive=str(static_control.ARCHIVE),
        files=[schemas.InboxFile(**f) for f in static_control.inbox_files()], running=running, running_since=since,
        last_run=schemas.BatchLogOut.model_validate(last) if last else None,
    )


@static.post("/run", response_model=schemas.BatchRunResult)
def run_static():
    """Load every JSON file in input/static now (CSVs -> master-data bulk loaders -> archive) and report."""
    result = static_control.run_now()
    with SessionLocal() as db:  # a fresh session: the rows were written by the batch process
        runs = static_control.logs_since(db, result["started_at"])
    return schemas.BatchRunResult(**result, runs=[schemas.BatchLogOut.model_validate(r) for r in runs])


@static.get("/logs", response_model=schemas.BatchLogPage)
def static_logs(
    status: Optional[Literal["SUCCESS", "PARTIAL", "FAILED"]] = None,
    q: Optional[str] = None,
    limit: int = Query(25, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    items, total, counts = static_control.list_logs(db, status, q, limit, offset)
    return schemas.BatchLogPage(items=[schemas.BatchLogOut.model_validate(r) for r in items], total=total, counts=counts)


@static.get("/logs/{batch_id}", response_model=schemas.BatchLogDetail)
def static_log(batch_id: int, db: Session = Depends(get_db)):
    row = static_control.get_log(db, batch_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"Static batch log #{batch_id} not found")
    return schemas.BatchLogDetail.model_validate(row)


# ---------------------------------------------------------------- historical telemetry loader (code: <project>/historical_loader)

historical = APIRouter(prefix="/api/batch/historical", tags=["batch"])


@historical.get("/options")
def historical_options(db: Session = Depends(get_db)):
    """Sites -> battery systems (with their EMS / HVAC units), the folders under input, and the feeds."""
    return historical_control.options(db)


@historical.post("/scan")
def historical_scan(payload: schemas.HistoricalLoadRequest):
    """Which files in the folder would be loaded as which feed, and whether they belong to the chosen system."""
    return historical_control.preview(payload.system_name, payload.folder, tuple(payload.feeds), payload.recursive,
                                      payload.ems_code, payload.hvac_code)


@historical.post("/run")
def historical_run(payload: schemas.HistoricalLoadRequest):
    """Start loading the selected files of the folder (runs as its own process); GET /status shows its progress."""
    return historical_control.start(payload.system_name, payload.folder, tuple(payload.feeds), payload.recursive,
                                    payload.ems_code, payload.hvac_code, payload.files)


@historical.get("/status")
def historical_status():
    return historical_control.status()


@historical.get("/logs", response_model=schemas.BatchLogPage)
def historical_logs(
    status: Optional[Literal["SUCCESS", "PARTIAL", "FAILED"]] = None,
    q: Optional[str] = None,
    limit: int = Query(25, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    items, total, counts = historical_control.list_logs(db, status, q, limit, offset)
    return schemas.BatchLogPage(items=[schemas.BatchLogOut.model_validate(r) for r in items], total=total, counts=counts)


# ---------------------------------------------------------------- historical file generator (code: <project>/historical_generator)

history_generator = APIRouter(prefix="/api/batch/history-generator", tags=["batch"])


@history_generator.get("/options")
def generator_options():
    """Battery systems that can be generated (master data present), their folders, and the default range."""
    return generator_control.options()


@history_generator.post("/preview")
def generator_preview(payload: schemas.GeneratorPreviewRequest):
    """A site's mapping (master data and the values used), the proposed scenario calendar and the module range."""
    return generator_control.preview(payload.battery_system_id, payload.date_from, payload.date_to, payload.overrides)


@history_generator.post("/run")
def generator_run(payload: schemas.GeneratorRunRequest):
    """Start generating the selected sites one after another (its own process); GET /status shows its progress."""
    return generator_control.start(payload.date_from, payload.date_to, payload.module_from,
                                   [s.model_dump() for s in payload.sites])


@history_generator.get("/status")
def generator_status():
    return generator_control.status()


@history_generator.get("/logs", response_model=schemas.BatchLogPage)
def generator_logs(
    status: Optional[Literal["SUCCESS", "PARTIAL", "FAILED"]] = None,
    limit: int = Query(25, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    items, total, counts = generator_control.list_logs(db, status, limit, offset)
    return schemas.BatchLogPage(items=[schemas.BatchLogOut.model_validate(r) for r in items], total=total, counts=counts)
