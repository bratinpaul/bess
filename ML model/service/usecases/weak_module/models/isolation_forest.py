"""Isolation Forest: rows that random splits isolate quickly are anomalous. Fitted once; scores new windows."""
from typing import Any, Optional

import numpy as np
from sklearn.ensemble import IsolationForest

from usecases.weak_module.models.base import BaseDetector, Detection


class IsolationForestDetector(BaseDetector):
    key = "isolation_forest"
    label = "Isolation Forest"
    param_specs = [
        {"name": "n_estimators", "label": "Trees", "type": "int", "default": 300, "min": 50, "max": 2000, "step": 50},
        {"name": "contamination", "label": "Expected anomaly share", "type": "float", "default": 0.05, "min": 0.005,
         "max": 0.4, "step": 0.005, "help": "Share of rows flagged as anomalous (the score threshold)."},
        {"name": "max_samples", "label": "Rows per tree (0 = auto)", "type": "int", "default": 0, "min": 0,
         "max": 100000, "step": 64},
        {"name": "max_features", "label": "Features per tree (share)", "type": "float", "default": 1.0, "min": 0.1,
         "max": 1.0, "step": 0.1},
    ]

    def __init__(self, params: Optional[dict] = None, seed: int = 42):
        super().__init__(params, seed)
        self.model: Optional[IsolationForest] = None

    def detect(self, X: np.ndarray) -> Detection:
        p = self.params
        self.model = IsolationForest(n_estimators=p["n_estimators"], contamination=p["contamination"],
                                     max_samples="auto" if p["max_samples"] == 0 else min(p["max_samples"], len(X)),
                                     max_features=p["max_features"], random_state=self.seed, n_jobs=4)
        self.model.fit(X)
        return self.score_new(X)

    def score_new(self, X: np.ndarray) -> Detection:
        score = -self.model.score_samples(X)  # higher = more anomalous
        flag = self.model.predict(X) == -1
        return Detection(score=score, flag=flag, info={"threshold": float(-self.model.offset_)})

    def state(self) -> dict[str, Any]:
        return {"params": self.params, "model": self.model}

    @classmethod
    def restore(cls, state: dict) -> "IsolationForestDetector":
        d = cls(state["params"])
        d.model = state["model"]
        return d
