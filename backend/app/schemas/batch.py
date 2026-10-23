from datetime import date, datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class BatchLogOut(BaseModel):
    """A batchlog row without the full report (list view)."""

    batch_id: int
    run_id: str
    file_name: str
    file_time: Optional[datetime] = None
    snapshot_time: Optional[datetime] = None
    status: str
    started_at: datetime
    finished_at: datetime
    duration_ms: int
    feeds_total: int
    feeds_loaded: int
    feeds_failed: int
    rows_total: int
    rows_inserted: int
    rows_updated: int
    rows_skipped: int
    feed_results: list[dict[str, Any]]
    warnings: list[str]
    id_changes: list[str]
    error_message: Optional[str] = None
    error_code: Optional[str] = None  # bess_common.errors.batch_error_code
    request_id: Optional[str] = None  # the run's X-Request-ID (search it in Admin -> Activity Log)
    archive_path: Optional[str] = None

    model_config = {"from_attributes": True}


class BatchLogDetail(BatchLogOut):
    api_url: Optional[str] = None
    host_name: Optional[str] = None
    report: Optional[dict[str, Any]] = None


class BatchLogPage(BaseModel):
    items: list[BatchLogOut]
    total: int
    # over all runs matching the status filter's period (not just this page)
    counts: dict[str, int]


class InboxFile(BaseModel):
    name: str
    size_bytes: int
    modified_at: datetime
    # named YYYY-MM-DD-HH-MM-SS.json - anything else is ignored by the batch
    valid_name: bool
    # not changed in the last few seconds, so the next run will take it
    ready: bool


class ScheduleInfo(BaseModel):
    task_name: str
    installed: bool
    status: Optional[str] = None
    next_run: Optional[str] = None
    last_run: Optional[str] = None
    last_result: Optional[str] = None
    repeat_every: Optional[str] = None


class BatchStatus(BaseModel):
    inbox: str
    archive: str
    files: list[InboxFile]
    # a run (scheduled or manual) is in progress
    running: bool
    running_since: Optional[str] = None
    schedule: ScheduleInfo
    last_run: Optional[BatchLogOut] = None


class BatchRunResult(BaseModel):
    started_at: datetime
    finished_at: datetime
    exit_code: int
    # another run held the lock, so this one did nothing
    busy: bool
    # the batchlog rows this run wrote
    runs: list[BatchLogOut]
    output: list[str]


# ---------------------------------------------------------------- snapshot simulator


class SimulatorRequest(BaseModel):
    # plant local time; rounded to the 5-minute grid (start up, end down)
    start: datetime
    end: datetime
    # same seed + same range = the same source days (repeatable); empty = random
    seed: Optional[int] = None
    # replace a file of the same name still waiting in the inbox
    overwrite: bool = False
    # restrict the historical days sampled from
    source_from: Optional[date] = None
    source_to: Optional[date] = None


class SimulatorResult(BaseModel):
    start: datetime
    end: datetime
    intervals: int
    written: int
    skipped_existing: int
    already_loaded: int
    first_file: Optional[str] = None
    last_file: Optional[str] = None
    source_days: dict[str, str]
    warnings: list[str]
    inbox: str


class SimulatorInfo(BaseModel):
    system_name: str
    source_days: list[date]
    module_days: list[date]
    latest_telemetry: Optional[datetime] = None
    inbox: str
    max_files: int
    interval_minutes: int


# ---------------------------------------------------------------- static data batch


class StaticBatchStatus(BaseModel):
    inbox: str
    archive: str
    files: list[InboxFile]
    running: bool
    running_since: Optional[str] = None
    last_run: Optional[BatchLogOut] = None


# ---------------------------------------------------------------- historical telemetry loader

HISTORICAL_FEEDS = ("bms", "pcs", "ems", "hvac", "module", "alarm", "dispatch")


class HistoricalLoadRequest(BaseModel):
    system_name: str = Field(min_length=1)
    # a folder inside <project>/input, e.g. "historical/Bhadla BESS"
    folder: str = Field(min_length=1)
    feeds: list[Literal["bms", "pcs", "ems", "hvac", "module", "alarm", "dispatch"]] = list(HISTORICAL_FEEDS)
    recursive: bool = True
    ems_code: Optional[str] = None
    hvac_code: Optional[str] = None
    # the files to load (names relative to the folder, as the scan returns them); None = all that pass the check
    files: Optional[list[str]] = None


# ---------------------------------------------------------------- historical generator


class GeneratorPreviewRequest(BaseModel):
    battery_system_id: int
    date_from: date
    date_to: date
    # mapping values for this run only (master data is not changed); see historical_generator/generator.OVERRIDES
    overrides: Optional[dict[str, Any]] = None


class GeneratorSiteJob(BaseModel):
    battery_system_id: int
    site_name: Optional[str] = None
    overrides: Optional[dict[str, Any]] = None
    # scenario days {heat: {date: degC}, monsoon: [date], low_insulation, maintenance: {date, start, end},
    # outage: {date, restart}}; None = proposed from the site's climate at generation time
    calendar: Optional[dict[str, Any]] = None


class GeneratorRunRequest(BaseModel):
    date_from: date
    date_to: date
    # module CSVs from this day to date_to (None = the last 30 days of the range)
    module_from: Optional[date] = None
    sites: list[GeneratorSiteJob] = Field(min_length=1)
