"""Interface of an anomaly detector for the weak module use case (one subclass per algorithm).

A detector works on already-scaled feature rows. detect() returns, per row, an anomaly score (higher = more
unusual) and a flag; DBSCAN also returns its cluster label (-1 = noise). A fitted detector can be saved inside the
run's artifact and used again on a new window (Isolation Forest scores new rows; DBSCAN, which can't place unseen
points, clusters the new window again with the same settings).
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, ClassVar, Optional

import numpy as np


class DetectionError(Exception):
    """Bad settings or data (the API answers 400)."""


@dataclass
class Detection:
    score: np.ndarray  # higher = more anomalous
    flag: np.ndarray  # bool
    label: Optional[np.ndarray] = None  # cluster label (DBSCAN; -1 = noise)
    info: dict[str, Any] = None  # e.g. eps used, number of clusters


class BaseDetector(ABC):
    key: ClassVar[str]
    label: ClassVar[str]
    # {name, label, type: int|float|choice, default, min, max, step, help?, choices?}
    param_specs: ClassVar[list[dict]]

    def __init__(self, params: Optional[dict] = None, seed: int = 42):
        self.params = self.clean_params(params or {})
        self.seed = seed

    @classmethod
    def clean_params(cls, params: dict) -> dict:
        out = {}
        for spec in cls.param_specs:
            value = params.get(spec["name"], spec["default"])
            if value in (None, ""):
                value = spec["default"]
            if spec["type"] == "choice":
                if value not in spec["choices"]:
                    raise DetectionError(f"{spec['label']} must be one of {', '.join(map(str, spec['choices']))}")
            else:
                value = int(value) if spec["type"] == "int" else float(value)
                if not spec["min"] <= value <= spec["max"]:
                    raise DetectionError(f"{spec['label']} must be between {spec['min']} and {spec['max']}")
            out[spec["name"]] = value
        unknown = set(params) - set(out)
        if unknown:
            raise DetectionError(f"Unknown parameter(s) for {cls.label}: {', '.join(sorted(unknown))}")
        return out

    @abstractmethod
    def detect(self, X: np.ndarray) -> Detection:
        """Fit on X and return the result for every row of X."""

    def score_new(self, X: np.ndarray) -> Detection:
        """Result for new rows with the fitted detector (default: fit again with the same settings)."""
        return self.detect(X)

    def state(self) -> dict:
        """What to keep in the run's artifact."""
        return {"params": self.params}
