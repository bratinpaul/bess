"""The anomaly detectors of the weak module use case."""
from usecases.weak_module.models.base import BaseDetector, Detection, DetectionError
from usecases.weak_module.models.dbscan import DbscanDetector
from usecases.weak_module.models.isolation_forest import IsolationForestDetector

DETECTORS: dict[str, type[BaseDetector]] = {d.key: d for d in (IsolationForestDetector, DbscanDetector)}

__all__ = ["BaseDetector", "Detection", "DetectionError", "DETECTORS", "DbscanDetector", "IsolationForestDetector"]
