"""DBSCAN: dense groups of similar rows form clusters; rows in no dense region are noise = anomalous.

eps (the neighbourhood radius, in scaled feature units) can be chosen automatically from the k-distance curve:
the distance of every row to its min_samples-th nearest neighbour, sorted; the knee of that curve (largest gap to
the straight line between its ends) separates dense rows from outliers. The anomaly score of a noise row is its
distance to the nearest core row relative to eps (clustered rows score 0).
"""
from typing import Optional

import numpy as np
from sklearn.cluster import DBSCAN
from sklearn.neighbors import NearestNeighbors

from usecases.weak_module.models.base import BaseDetector, Detection, DetectionError


def knee_eps(X: np.ndarray, k: int) -> float:
    nn = NearestNeighbors(n_neighbors=min(k + 1, len(X))).fit(X)
    dist = np.sort(nn.kneighbors(X)[0][:, -1])
    n = len(dist)
    if n < 3 or dist[-1] == dist[0]:
        return float(dist[-1] or 0.5)
    x = np.linspace(0, 1, n)
    y = (dist - dist[0]) / (dist[-1] - dist[0])
    return float(dist[int(np.argmax(x - y))])  # the curve bends up: furthest below the chord


class DbscanDetector(BaseDetector):
    key = "dbscan"
    label = "DBSCAN"
    param_specs = [
        {"name": "eps", "label": "Neighbourhood radius eps (0 = auto)", "type": "float", "default": 0.0, "min": 0.0,
         "max": 50.0, "step": 0.05, "help": "In scaled feature units; auto picks the knee of the k-distance curve."},
        {"name": "min_samples", "label": "Min rows in a neighbourhood (0 = auto)", "type": "int", "default": 0,
         "min": 0, "max": 2000, "step": 1,
         "help": "Auto = 2 x the rows per module, so a cluster needs at least two modules' worth of rows: a module "
                 "that deviates on every day can't form a cluster of its own and shows up as noise."},
        {"name": "eps_scale", "label": "Auto eps multiplier", "type": "float", "default": 1.0, "min": 0.2, "max": 5.0,
         "step": 0.1, "help": "Scales the automatic eps: below 1 flags more rows as noise, above 1 fewer."},
        {"name": "metric", "label": "Distance", "type": "choice", "default": "euclidean",
         "choices": ["euclidean", "manhattan", "chebyshev"]},
    ]

    def __init__(self, params: Optional[dict] = None, seed: int = 42):
        super().__init__(params, seed)
        self.eps_used: Optional[float] = None

    def detect(self, X: np.ndarray, eps: Optional[float] = None) -> Detection:
        p = self.params
        if p["min_samples"] < 2:
            raise DetectionError("min_samples must be at least 2 (or 0 for auto)")
        if len(X) < p["min_samples"]:
            raise DetectionError(f"DBSCAN needs at least {p['min_samples']} rows (min_samples)")
        eps = eps or p["eps"] or knee_eps(X, p["min_samples"]) * p["eps_scale"]
        if eps <= 0:
            raise DetectionError("eps must be positive")
        self.eps_used = float(eps)
        model = DBSCAN(eps=eps, min_samples=p["min_samples"], metric=p["metric"], n_jobs=4).fit(X)
        labels = model.labels_
        noise = labels == -1
        score = np.zeros(len(X))
        core = model.core_sample_indices_
        if noise.any() and len(core):
            nn = NearestNeighbors(n_neighbors=1, metric=p["metric"]).fit(X[core])
            score[noise] = nn.kneighbors(X[noise])[0][:, 0] / eps
        elif noise.any():
            score[noise] = 1.0
        clusters = len(set(labels) - {-1})
        return Detection(score=score, flag=noise, label=labels, info={"eps": self.eps_used, "clusters": clusters})

    def score_new(self, X: np.ndarray) -> Detection:
        """DBSCAN can't place unseen rows: cluster the new window with the eps the train run used."""
        return self.detect(X, eps=self.eps_used)

    def state(self) -> dict:
        return {"params": self.params, "eps_used": self.eps_used}

    @classmethod
    def restore(cls, state: dict) -> "DbscanDetector":
        d = cls(state["params"])
        d.eps_used = state["eps_used"]
        return d
