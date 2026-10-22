"""Heat-load prediction (thermal design) API (mounted at /heatload): options, runs (compute / list / detail / delete) and
the viewer's reads (ledger, daily roll-up, forecast issues / trajectories / fixed-horizon series)."""
from datetime import date
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from core.db import engine
from usecases.heatload import data as D
from usecases.heatload import store
from usecases.heatload.balance import BalanceSettings
from usecases.heatload.design import DesignSettings
from usecases.heatload.forecast import ForecastSettings
from usecases.heatload.run import RunConfig, run

USE_CASE = "heatload"
PREFIX = "heatload"
router = APIRouter(tags=["Heat-load prediction / thermal design"])


class RunRequest(BaseModel):
    system_ids: list[int] = Field(min_length=1)
    date_from: date
    date_to: date
    run_name: Optional[str] = Field(default=None, max_length=120)
    # heat balance
    measured_reference: Literal["heat_load_sensor", "cooling_delivered"] = "heat_load_sensor"
    envelope_area_m2: float = Field(default=74.0, gt=0, le=10_000)
    u_value_w_m2k: float = Field(default=0.5, ge=0, le=10)
    sunlit_area_m2: float = Field(default=22.0, ge=0, le=10_000)
    absorptivity: float = Field(default=0.6, ge=0, le=1)
    pcs_inside: bool = True
    aux_inside: bool = True
    thermal_mass_kj_k_per_kwh: float = Field(default=7.0, ge=0, le=100)
    solar_source: Literal["auto", "clear_sky", "none"] = "auto"
    train_frac: float = Field(default=0.75, ge=0.3, le=0.95)
    # forecast
    horizons: list[int] = Field(default=[15, 30, 60, 120, 240])
    plan_source: Literal["scheduled", "typical", "oracle"] = "scheduled"
    issue_every_min: int = Field(default=30, ge=5, le=360)
    n_estimators: int = Field(default=300, ge=20, le=3000)
    learning_rate: float = Field(default=0.05, gt=0, le=1)
    num_leaves: int = Field(default=31, ge=4, le=512)
    # design
    design_ambient_c: Optional[float] = Field(default=None, ge=-20, le=70)
    design_ghi_wm2: float = Field(default=1000.0, ge=0, le=1400)
    design_soc_pct: float = Field(default=15.0, ge=0, le=100)
    design_cell_temp_c: float = Field(default=35.0, ge=-20, le=70)
    internal_setpoint_c: float = Field(default=25.0, ge=0, le=50)
    eol_resistance_pct: Optional[float] = Field(default=None, ge=100, le=500)
    margin_pct: float = Field(default=15.0, ge=0, le=100)
    redundancy: int = Field(default=1, ge=0, le=5)
    unit_capacity_kw: Optional[float] = Field(default=None, gt=0, le=10_000)
    capacity_derate_pct_per_c: float = Field(default=1.0, ge=0, le=10)
    coincidence: float = Field(default=1.0, ge=0, le=1)
    use_calibrated: bool = True


def status() -> dict:
    runs = [r for r in store.list_runs(engine, 5) if r["status"] == "COMPLETED"]
    return {"latest_run": runs[0]["run_id"] if runs else None}


def _config(b: RunRequest) -> RunConfig:
    horizons = sorted({int(h) for h in b.horizons if 5 <= int(h) <= 24 * 60 and int(h) % D.STEP_MIN == 0})
    if not horizons:
        raise HTTPException(status_code=400, detail="Give at least one horizon (a multiple of 5 min, up to 24 h)")
    return RunConfig(
        system_ids=b.system_ids, date_from=b.date_from, date_to=b.date_to,
        balance=BalanceSettings(measured_reference=b.measured_reference, envelope_area_m2=b.envelope_area_m2,
                                u_value_w_m2k=b.u_value_w_m2k, sunlit_area_m2=b.sunlit_area_m2, absorptivity=b.absorptivity,
                                pcs_inside=b.pcs_inside, aux_inside=b.aux_inside,
                                thermal_mass_kj_k_per_kwh=b.thermal_mass_kj_k_per_kwh, solar_source=b.solar_source,
                                train_frac=b.train_frac, internal_setpoint_c=b.internal_setpoint_c),
        forecast=ForecastSettings(horizons=horizons, plan_source=b.plan_source, issue_every_min=b.issue_every_min,
                                  n_estimators=b.n_estimators, learning_rate=b.learning_rate, num_leaves=b.num_leaves),
        design=DesignSettings(design_ambient_c=b.design_ambient_c, design_ghi_wm2=b.design_ghi_wm2,
                              design_soc_pct=b.design_soc_pct, design_cell_temp_c=b.design_cell_temp_c,
                              internal_setpoint_c=b.internal_setpoint_c, eol_resistance_pct=b.eol_resistance_pct,
                              margin_pct=b.margin_pct, redundancy=b.redundancy, unit_capacity_kw=b.unit_capacity_kw,
                              capacity_derate_pct_per_c=b.capacity_derate_pct_per_c, coincidence=b.coincidence,
                              use_calibrated=b.use_calibrated))


@router.get("/options")
def options():
    systems = D.systems(engine)
    first = min((s["first_day"] for s in systems), default=date.today().isoformat())
    last = max((s["last_day"] for s in systems), default=date.today().isoformat())
    defaults = RunRequest(system_ids=[s["system_id"] for s in systems] or [0], date_from=first, date_to=last)
    return {
        "systems": systems,
        "defaults": defaults.model_dump(mode="json"),
        "references": [
            {"key": "heat_load_sensor", "label": "HVAC battery heat-load reading (battery_heat_load_kw)"},
            {"key": "cooling_delivered", "label": "Cooling delivered (cooling_capacity_kw, 0 when idle)"},
        ],
        "plan_sources": [
            {"key": "scheduled", "label": "EMS dispatch schedule (dispatch_event), typical day where none"},
            {"key": "typical", "label": "Typical day (median power per 5-min slot of the training days)"},
            {"key": "oracle", "label": "Realized power (perfect schedule - the upper bound of plan value)"},
        ],
    }


@router.post("/runs")
def create_run(body: RunRequest):
    if body.date_from > body.date_to:
        raise HTTPException(status_code=400, detail="date_from must be on or before date_to")
    known = {s["system_id"] for s in D.systems(engine)}
    unknown = [s for s in body.system_ids if s not in known]
    if unknown:
        raise HTTPException(status_code=400, detail=f"No BMS / PCS / EMS / HVAC telemetry for battery system(s) {unknown}")
    cfg = _config(body)
    run_id = store.start_run(engine, {"name": body.run_name, "systems": body.system_ids, "date_from": body.date_from,
                                      "date_to": body.date_to, "params": body.model_dump(mode="json")})
    try:
        result = run(engine, cfg)
        store.complete_run(engine, run_id, result)
    except D.HeatLoadError as exc:
        store.fail_run(engine, run_id, str(exc))
        raise HTTPException(status_code=400, detail={"message": str(exc), "run_id": run_id})
    except Exception as exc:  # noqa: BLE001 - keep a record of unexpected failures
        store.fail_run(engine, run_id, f"{type(exc).__name__}: {exc}")
        raise HTTPException(status_code=500, detail={"message": f"Run failed: {exc}", "run_id": run_id})
    return store.get_run(engine, run_id)


@router.get("/runs")
def runs(limit: int = Query(100, ge=1, le=500)):
    return store.list_runs(engine, limit)


@router.get("/runs/{run_id}")
def run_detail(run_id: int):
    r = store.get_run(engine, run_id)
    if not r:
        raise HTTPException(status_code=404, detail=f"Run #{run_id} not found")
    return r


@router.delete("/runs/{run_id}", status_code=204)
def delete_run(run_id: int):
    if not store.delete_run(engine, run_id):
        raise HTTPException(status_code=404, detail=f"Run #{run_id} not found")


def _check(run_id: int, system_id: int) -> None:
    r = store.get_run(engine, run_id)
    if not r:
        raise HTTPException(status_code=404, detail=f"Run #{run_id} not found")
    if system_id not in (r["system_ids"] or []):
        raise HTTPException(status_code=404, detail=f"Run #{run_id} doesn't cover battery system {system_id}")


@router.get("/runs/{run_id}/ledger")
def run_ledger(run_id: int, system_id: int, day_from: date, day_to: Optional[date] = None):
    _check(run_id, system_id)
    return store.ledger(engine, run_id, system_id, day_from, day_to or day_from)


@router.get("/runs/{run_id}/daily")
def run_daily(run_id: int, system_id: int):
    """The time_bucket daily roll-up of the ledger (v_heatload_daily)."""
    _check(run_id, system_id)
    return store.daily(engine, run_id, system_id)


@router.get("/runs/{run_id}/issues")
def run_issues(run_id: int, system_id: int):
    _check(run_id, system_id)
    return store.issues(engine, run_id, system_id)


@router.get("/runs/{run_id}/trajectory")
def run_trajectory(run_id: int, system_id: int, issued_at: str):
    _check(run_id, system_id)
    return store.trajectory(engine, run_id, system_id, issued_at)


@router.get("/runs/{run_id}/horizon")
def run_horizon(run_id: int, system_id: int, horizon_min: int, day_from: date, day_to: Optional[date] = None):
    _check(run_id, system_id)
    return store.horizon_series(engine, run_id, system_id, horizon_min, day_from, day_to or day_from)
