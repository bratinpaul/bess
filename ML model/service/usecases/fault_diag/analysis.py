"""Reliability analytics over the confirmed fault layer: overview, Pareto (vital few) and the Ishikawa / fishbone
root-cause view.

Fishbone: the effect is one fault class, a subsystem or every fault. Causes come from
    confirmed   fault_episode.root_cause_confirmed (split on ';' and '/'), weighted by episode count
    repair      maintenance_action.component of the episodes (what had to be serviced)
    context     fault_episode.operating_context (what the plant was doing)
    catalog     fault_catalog.typical_root_cause (the a-priori causes, shown even with no episode)
and are sorted into the 6M bones (Man, Machine, Method, Material, Measurement, Mother Nature / Environment) by keyword
score. Symptoms (fault_signature) and the trained model's strongest features are returned beside the diagram as the
evidence trail, not as causes.
"""
import re
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd

from usecases.fault_diag import data as D
from bess_common.errors import BadRequest, NotFound

BONES = ["Man", "Machine", "Method", "Material", "Measurement", "Environment"]
BONE_HINT = {
    "Man": "People, maintenance practice, procedures",
    "Machine": "Equipment and components",
    "Method": "Operation, dispatch, control and protection settings",
    "Material": "Cells, parts and consumables",
    "Measurement": "Sensing, communication and data",
    "Environment": "Ambient, grid and site conditions",
}
KEYWORDS = {
    "Man": ["operator", "service due", "maintenance", "procedure", "training", "human", "manual", "workmanship",
            "installation"],
    "Measurement": ["sensor", "sense", "calibrat", "drift", "telemetry", "data", "comm", "can ", "can bus", "modbus",
                    "ethercat", "frame", "handshake", "network", "scada", "gateway", "link", "feed", "stale", "price",
                    "estimat", "noise", "bmu"],
    "Environment": ["ambient", "humid", "moisture", "dust", "grid", "frequency", "disturbance", "weather", "warm",
                    "market operator", "ingress", "outage", "earth leakage"],
    "Material": ["cell", "defect", "manufactur", "dendrite", "separator", "capacitor", "refrigerant", "filter",
                 "insulation", "leak", "aging", "degradation", "weak", "fouling", "soc divergence"],
    "Method": ["dispatch", "ramp", "setpoint", "limit", "headroom", "curtail", "protection", "setting", "charging",
               "charge", "discharge", "control", "strategy", "regulation", "sizing", "undersiz", "design", "staging", "reactive",
               "overload", "high load", "peak", "cycling", "response", "demand", "light load"],
    "Machine": ["pump", "fan", "compressor", "balancing", "fet", "busbar", "joint", "cooling", "hvac", "pcs",
                "inverter", "controller", "connector", "contactor", "igbt", "heatsink", "valve", "cut-out", "air lock",
                "bearing", "module", "string", "gateway", "loop", "pressure", "dc bus"],
}
PRIORITY = ["Man", "Measurement", "Environment", "Material", "Machine", "Method"]
MEASURES = {"count": ("Episodes", ""), "downtime_min": ("Downtime", "min"), "energy_lost_kwh": ("Energy lost", "kWh"),
            "cost_usd": ("Repair cost", "$"), "labor_hours": ("Labour", "h"), "alarms": ("Linked alarms", "")}
GROUPS = {"fault": "Fault class", "subsystem": "Subsystem", "category": "Category", "root_cause": "Confirmed root cause",
          "component": "Serviced component", "asset": "Asset", "alarm_code": "Alarm code", "context": "Operating context"}


def _filter(eps: pd.DataFrame, date_from: Optional[date], date_to: Optional[date], system_id: Optional[int],
            systems: Optional[set] = None) -> pd.DataFrame:
    if systems is not None:  # tenant-scoped caller: only episodes of its tenant's systems (filed or telemetry system)
        eps = eps[eps["system_id"].isin(systems) | eps["telemetry_system_id"].isin(systems)]
    if date_from:
        eps = eps[eps["detected_ts"] >= pd.Timestamp(date_from, tz=D.TZ)]
    if date_to:
        eps = eps[eps["detected_ts"] < pd.Timestamp(date_to, tz=D.TZ) + pd.Timedelta(days=1)]
    if system_id:
        eps = eps[(eps["system_id"] == system_id) | (eps["telemetry_system_id"] == system_id)]
    return eps


def overview(engine, date_from=None, date_to=None, system_id=None, systems=None) -> dict:
    eps = _filter(D.episodes(engine), date_from, date_to, system_id, systems)
    cat = D.catalog(engine)
    lead = (eps["detected_ts"] - eps["onset_ts"]).dt.total_seconds() / 60
    dur = (eps["resolved_ts"] - eps["detected_ts"]).dt.total_seconds() / 3600
    by_sub = []
    for sub, g in eps.groupby("subsystem"):
        by_sub.append({"subsystem": sub, "episodes": int(len(g)), "classes": int(g["fault_code"].nunique()),
                       "downtime_min": float(g["downtime_min"].sum()), "energy_lost_kwh": float(g["energy_lost_kwh"].sum()),
                       "safety_critical": int(g["is_safety_critical"].fillna(False).sum())})
    daily = eps.groupby([eps["detected_ts"].dt.strftime("%Y-%m-%d"), "subsystem"]).size().unstack(fill_value=0)
    return {
        "episodes": int(len(eps)), "classes": int(eps["fault_code"].nunique()), "catalog_classes": int(len(cat)),
        "safety_critical": int(eps["is_safety_critical"].fillna(False).sum()),
        "ongoing": int(eps["is_ongoing"].fillna(False).sum()),
        "downtime_min": float(eps["downtime_min"].sum()), "energy_lost_kwh": float(eps["energy_lost_kwh"].sum()),
        "repair_cost_usd": float(eps["cost_usd"].sum()), "work_orders": int(eps["action_type"].notna().sum()),
        "mttr_h": D._num(dur.mean()), "mean_lead_min": D._num(lead.mean()), "median_lead_min": D._num(lead.median()),
        "confirmed_by_repair": int((eps["fault_confirmed"] == True).sum()),  # noqa: E712
        "date_from": eps["detected_ts"].min().date().isoformat() if len(eps) else None,
        "date_to": eps["detected_ts"].max().date().isoformat() if len(eps) else None,
        "by_subsystem": by_sub,
        "daily": {"days": list(daily.index), "series": {c: [int(v) for v in daily[c]] for c in daily.columns}},
    }


def _explode(eps: pd.DataFrame, group_by: str) -> pd.DataFrame:
    e = eps.copy()
    if group_by == "fault":
        e["key"] = e["fault_code"]
    elif group_by == "subsystem":
        e["key"] = e["subsystem"]
    elif group_by == "category":
        e["key"] = e["category"]
    elif group_by == "root_cause":
        e["key"] = e["root_cause_confirmed"].fillna("(not recorded)")
    elif group_by == "component":
        e["key"] = e["component"].fillna("(no work order)")
    elif group_by == "asset":
        e["key"] = e["asset_code"].fillna("(unknown)")
    elif group_by == "context":
        e["key"] = e["operating_context"].fillna("(not recorded)")
    elif group_by == "alarm_code":
        e["key"] = e["all_alarms"].apply(lambda v: v or ["(no alarm)"])
        e = e.explode("key")
    else:
        raise BadRequest(f"Unknown grouping '{group_by}'")
    return e


def pareto(engine, measure: str = "count", group_by: str = "fault", date_from=None, date_to=None, system_id=None,
           cutoff: float = 0.8, systems=None) -> dict:
    eps = _filter(D.episodes(engine), date_from, date_to, system_id, systems)
    cat = D.catalog(engine).set_index("fault_code")
    e = _explode(eps, group_by)
    e["n_alarms"] = e["alarm_ids"].apply(len)
    col = {"count": None, "alarms": "n_alarms"}.get(measure, measure)
    g = e.groupby("key")
    vals = g.size() if col is None else g[col].sum()
    if group_by == "alarm_code" and measure in ("count", "alarms"):
        vals = g.size()
    vals = vals.astype(float).sort_values(ascending=False)
    vals = vals[vals > 0]
    total = float(vals.sum())
    items, cum = [], 0.0
    for k, v in vals.items():
        prev = cum
        cum += v
        sub = g.get_group(k)
        items.append({
            "key": k, "label": f"{k} · {cat.at[k, 'fault_name']}" if group_by == "fault" and k in cat.index else k,
            "value": v, "share": v / total if total else 0, "cum_share": cum / total if total else 0,
            "vital_few": prev / total < cutoff if total else False, "episodes": int(sub["episode_id"].nunique()),
            "subsystem": cat.at[k, "subsystem"] if group_by == "fault" and k in cat.index else
            (sub["subsystem"].mode().iat[0] if len(sub) else None),
            "safety_critical": bool(sub["is_safety_critical"].fillna(False).any()),
            "faults": sorted(sub["fault_code"].unique().tolist())})
    label, unit = MEASURES[measure]
    return {"measure": measure, "measure_label": label, "unit": unit, "group_by": group_by,
            "group_label": GROUPS[group_by], "total": total, "cutoff": cutoff, "items": items,
            "vital_few": sum(1 for i in items if i["vital_few"]), "n_groups": len(items)}


def _bone(text: str) -> str:
    t = text.lower()
    score = {b: sum(1 for k in KEYWORDS[b] if re.search(r"\b" + re.escape(k.strip()), t)) for b in BONES}
    best = max(score.values())
    if best == 0:
        return "Machine"
    return next(b for b in PRIORITY if score[b] == best)


def _split(text: Optional[str], seps=r";|\s/\s") -> list[str]:
    if not text or not isinstance(text, str):
        return []
    parts = [p.strip(" .") for p in re.split(seps, text)]
    return [p[0].upper() + p[1:] for p in parts if len(p) > 2]


def fishbone(engine, effect: str = "ALL", date_from=None, date_to=None, system_id=None,
             model_insight: Optional[dict] = None, systems=None) -> dict:
    eps = _filter(D.episodes(engine), date_from, date_to, system_id, systems)
    cat = D.catalog(engine)
    sigs = D.signatures(engine)
    if effect.startswith("SUB:"):
        sub = effect[4:]
        codes = set(cat.loc[cat["subsystem"] == sub, "fault_code"])
        title, subtitle = f"{sub} faults", f"{len(codes)} fault classes in the {sub} subsystem"
    elif effect == "ALL":
        codes = set(cat["fault_code"]) - {"F-NONE"}
        title, subtitle = "All plant faults", f"{len(codes)} fault classes"
    else:
        codes = {effect}
        r = cat[cat["fault_code"] == effect]
        if r.empty:
            raise NotFound(f"Unknown fault {effect}")
        title, subtitle = r["fault_name"].iat[0], f"{effect} · {r['subsystem'].iat[0]} · {r['category'].iat[0]}"
    e = eps[eps["fault_code"].isin(codes)]
    c = cat[cat["fault_code"].isin(codes)]

    causes: dict[tuple, dict] = {}

    def add(text: str, source: str, n: int, fault: str, bone: Optional[str] = None, extra: Optional[dict] = None):
        b = bone or _bone(text)
        k = (b, text.lower())
        it = causes.setdefault(k, {"bone": b, "cause": text, "episodes": 0, "sources": set(), "faults": set(),
                                   "downtime_min": 0.0, "energy_lost_kwh": 0.0})
        it["episodes"] += n
        it["sources"].add(source)
        it["faults"].add(fault)
        if extra:
            it["downtime_min"] += extra.get("downtime_min", 0.0)
            it["energy_lost_kwh"] += extra.get("energy_lost_kwh", 0.0)

    for r in e.itertuples():
        ex = {"downtime_min": float(r.downtime_min or 0), "energy_lost_kwh": float(r.energy_lost_kwh or 0)}
        for p in _split(r.root_cause_confirmed):
            add(p, "confirmed", 1, r.fault_code, extra=ex)
        if isinstance(r.component, str) and r.component:
            for p in _split(r.component, r",|\s/\s"):
                add(p, "repair", 1, r.fault_code, bone="Material" if _bone(p) == "Material" else "Machine")
        if isinstance(r.operating_context, str) and r.operating_context:
            ctx = r.operating_context
            add(f"During {ctx.lower()}", "context", 1, r.fault_code, bone="Environment" if _bone(ctx) == "Environment" else "Method")
    for r in c.itertuples():
        for p in _split(r.typical_root_cause, r",|;|\s/\s"):
            add(p, "catalog", 0, r.fault_code)
    # maintenance practice: ineffective repairs and repeat faults on the same asset point at people / procedure
    if not e.empty:
        rep = e.groupby(["fault_code", "asset_code"]).size()
        for (fc, asset), n in rep.items():
            if n >= 3:
                add(f"Repeat fault on {asset} ({n}×) - fix not holding", "pattern", 0, fc, bone="Man")
        bad = e[e["effective"] == False]  # noqa: E712
        for r in bad.itertuples():
            add(f"Ineffective repair ({r.component or r.action_type})", "pattern", 1, r.fault_code, bone="Man")
    bones = []
    for b in BONES:
        items = [v for v in causes.values() if v["bone"] == b]
        items.sort(key=lambda v: (-v["episodes"], -v["downtime_min"], v["cause"]))
        # cause mentions in confirmed episodes (an episode with two causes counts on both)
        bones.append({"bone": b, "hint": BONE_HINT[b], "episodes": int(sum(v["episodes"] for v in items if "confirmed" in v["sources"])),
                      "causes": [{**v, "sources": sorted(v["sources"]), "faults": sorted(v["faults"])} for v in items]})
    symptoms = sigs[sigs["fault_code"].isin(codes)].sort_values("weight", ascending=False)
    sym = [{"fault_code": s.fault_code, "signal": s.signal, "kind": s.signal_kind, "operator": s.operator,
            "threshold": D._num(s.threshold), "unit": s.unit, "weight": float(s.weight),
            "available": s.signal not in D.UNAVAILABLE} for s in symptoms.itertuples()]
    actions = [{"fault_code": r.fault_code, "fault_name": r.fault_name, "action": r.recommended_action,
                "symptoms": r.typical_symptoms, "standard": r.standard_ref, "safety_critical": bool(r.is_safety_critical)}
               for r in c.itertuples()]
    stats = {"episodes": int(len(e)), "downtime_min": float(e["downtime_min"].sum()),
             "energy_lost_kwh": float(e["energy_lost_kwh"].sum()), "repair_cost_usd": float(e["cost_usd"].sum()),
             "classes_seen": int(e["fault_code"].nunique()), "classes": len(codes),
             "mean_lead_min": D._num(((e["detected_ts"] - e["onset_ts"]).dt.total_seconds() / 60).mean())}
    return {"effect": effect, "title": title, "subtitle": subtitle, "stats": stats, "bones": bones, "symptoms": sym,
            "actions": actions, "model": model_insight}


def effects(engine) -> list[dict]:
    cat = D.catalog(engine)
    eps = D.episodes(engine)
    n = eps["fault_code"].value_counts()
    out = [{"key": "ALL", "label": "All faults", "episodes": int(len(eps))}]
    for sub in sorted(cat["subsystem"].unique()):
        codes = cat.loc[cat["subsystem"] == sub, "fault_code"]
        out.append({"key": f"SUB:{sub}", "label": f"{sub} subsystem", "episodes": int(n.reindex(codes).fillna(0).sum())})
    for r in cat.itertuples():
        if r.fault_code != "F-NONE":
            out.append({"key": r.fault_code, "label": f"{r.fault_code} · {r.fault_name}", "episodes": int(n.get(r.fault_code, 0)),
                        "subsystem": r.subsystem})
    return out
