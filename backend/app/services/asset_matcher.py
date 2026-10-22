"""Fuzzy-match an asset reported by a source system (e.g. 'Pack' / 'PACK-01') to its master-data record.

Source systems use short codes that differ from the master-data names:

    PACK-01 -> battery_pack    01-01-01-PACK-01        MOD-07  -> battery_module 01-01-01-01-MODULE-7
    PCS-01  -> pcs             01-01-PCS-01            BESS-01 -> battery_system 01-BATTERY-01
    EMS-01  -> ems_controller  EMS-01 (exact)          HVAC-01 -> hvac_unit      HVAC-01 (exact)

Matching, per candidate record of the asset's table:
  1.0   exact      same letters and digits, ignoring case and punctuation
  0.9   fuzzy      same kind word (MOD ~ MODULE, BESS ~ BATTERY, ...) and the same trailing number
  <0.85 fuzzy      plain string similarity, scaled down so it never beats a number match
The best candidate wins if it scores at least MIN_SCORE and clearly beats the runner-up; otherwise the
row is reported with the closest names so the code (or the master data) can be fixed.
"""
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Optional

from sqlalchemy.orm import Session

from app import models

MIN_SCORE = 0.75
MARGIN = 0.05

# reported asset_type (normalised) -> master-data table
TYPE_ALIASES = {
    "system": "battery_system", "bess": "battery_system", "battery": "battery_system", "battery system": "battery_system",
    "container": "battery_container", "enclosure": "battery_container",
    "pack": "battery_pack", "rack": "battery_pack", "battery pack": "battery_pack",
    "module": "battery_module", "cell": "battery_module", "battery module": "battery_module",
    "inverter": "pcs", "pcs": "pcs", "converter": "pcs",
    "site controller": "ems_controller", "ems": "ems_controller", "controller": "ems_controller",
    "hvac unit": "hvac_unit", "hvac": "hvac_unit", "chiller": "hvac_unit", "cooling unit": "hvac_unit",
}
# when the asset type is missing or unknown, where each source's assets live
SOURCE_TYPES = {
    "PCS": ["pcs"],
    "EMS": ["ems_controller"],
    "HVAC": ["hvac_unit"],
    "BMS": ["battery_system", "battery_container", "battery_pack", "battery_module"],
}
# kind words that mean the same thing
WORDS = {"BESS": "BATTERY", "BAT": "BATTERY", "BATT": "BATTERY", "SYS": "SYSTEM", "MOD": "MODULE", "INV": "PCS",
         "INVERTER": "PCS", "CTRL": "CONTROLLER", "HAVC": "HVAC", "CONT": "CONTAINER", "CNT": "CONTAINER"}

LABELS = {
    "battery_system": "Battery System", "battery_container": "Container", "battery_pack": "Pack",
    "battery_module": "Module", "pcs": "PCS", "ems_controller": "EMS", "hvac_unit": "HVAC",
}


@dataclass(frozen=True)
class Candidate:
    asset_type: str
    asset_id: int
    name: str
    battery_system_id: Optional[int]


@dataclass(frozen=True)
class Match:
    asset_type: str
    asset_id: int
    name: str
    battery_system_id: Optional[int]
    method: str  # exact / fuzzy
    score: float


class AssetMatchError(ValueError):
    pass


def _norm(text: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", text.upper())


def _kind_and_number(text: str) -> tuple[Optional[str], Optional[int]]:
    """'01-01-01-PACK-01' -> ('PACK', 1); 'MOD-07' -> ('MODULE', 7); 'BESS-01' -> ('BATTERY', 1)."""
    words = re.findall(r"[A-Z]+", text.upper())
    numbers = re.findall(r"\d+", text)
    kind = WORDS.get(words[-1], words[-1]) if words else None
    return kind, (int(numbers[-1]) if numbers else None)


def _same_kind(a: Optional[str], b: Optional[str]) -> bool:
    if not a or not b:
        return False
    return a == b or (min(len(a), len(b)) >= 3 and (a.startswith(b) or b.startswith(a)))


def _score(code: str, name: str) -> tuple[float, str]:
    if _norm(code) == _norm(name):
        return 1.0, "exact"
    code_kind, code_no = _kind_and_number(code)
    name_kind, name_no = _kind_and_number(name)
    if code_no is not None and code_no == name_no and _same_kind(code_kind, name_kind):
        return 0.9, "fuzzy"
    return SequenceMatcher(None, _norm(code), _norm(name)).ratio() * 0.85, "fuzzy"


class AssetMatcher:
    """Loads every candidate record once; reuse it for a whole upload."""

    def __init__(self, db: Session):
        containers = {c.container_id: c.battery_system_id for c in db.query(models.BatteryContainer)}
        packs = {p.pack_id: containers.get(p.container_id) for p in db.query(models.BatteryPack)}
        self.candidates: dict[str, list[Candidate]] = {
            "battery_system": [Candidate("battery_system", s.battery_system_id, s.system_name, s.battery_system_id)
                               for s in db.query(models.BatterySystem)],
            "battery_container": [Candidate("battery_container", c.container_id, c.container_number or f"Container {c.container_id}",
                                            c.battery_system_id) for c in db.query(models.BatteryContainer)],
            "battery_pack": [Candidate("battery_pack", p.pack_id, p.pack_number or f"Pack {p.pack_id}", packs.get(p.pack_id))
                             for p in db.query(models.BatteryPack)],
            "battery_module": [Candidate("battery_module", m.module_id, m.serial_number or f"Module {m.module_id}",
                                         packs.get(m.pack_id)) for m in db.query(models.BatteryModule)],
            "pcs": [Candidate("pcs", p.pcs_id, p.pcs_code, p.system_id) for p in db.query(models.Pcs)],
            "ems_controller": [Candidate("ems_controller", e.ems_id, e.ems_code, e.battery_system_id)
                               for e in db.query(models.EmsController)],
            "hvac_unit": [Candidate("hvac_unit", h.hvac_id, h.hvac_code, h.battery_system_id) for h in db.query(models.HvacUnit)],
        }

    def types_for(self, asset_type: Optional[str], source: Optional[str]) -> list[str]:
        mapped = TYPE_ALIASES.get((asset_type or "").strip().lower())
        if mapped:
            return [mapped]
        return SOURCE_TYPES.get((source or "").upper(), list(self.candidates))

    def get(self, asset_type: str, asset_id: int) -> Optional[Candidate]:
        return next((c for c in self.candidates.get(asset_type, []) if c.asset_id == asset_id), None)

    def match(self, asset_code: str, asset_type: Optional[str] = None, source: Optional[str] = None) -> Match:
        types = self.types_for(asset_type, source)
        scored = sorted(
            ((*_score(asset_code, c.name), c) for t in types for c in self.candidates.get(t, [])),
            key=lambda x: -x[0],
        )
        where = ", ".join(LABELS.get(t, t) for t in types)
        if not scored:
            raise AssetMatchError(f"no {where} records to match asset '{asset_code}' against")
        best_score, method, best = scored[0]
        runner_up = scored[1][0] if len(scored) > 1 else 0.0
        closest = ", ".join(f"{c.name} ({s:.2f})" for s, _, c in scored[:3])
        if best_score < MIN_SCORE:
            raise AssetMatchError(f"asset '{asset_code}' matches no {where} (closest: {closest})")
        if best_score - runner_up < MARGIN and best_score < 1.0:
            raise AssetMatchError(f"asset '{asset_code}' is ambiguous (closest: {closest})")
        return Match(best.asset_type, best.asset_id, best.name, best.battery_system_id, method, round(best_score, 3))
