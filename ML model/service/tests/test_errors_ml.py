"""Exception management in the ML service (exception plan phase 3): use-case errors are AppErrors answered 400 with their
own text, training runs go through run_guard (failure recorded on the run, run_id in the body), unexpected failures are a
generic 500 with the stack trace in the log, and missing model files never show a path. The RUL training endpoint
stands in for all use cases; its store and trainer are replaced, so nothing is trained or written."""
import importlib
import logging
import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bess_common.auth import create_access_token  # noqa: E402
from bess_common.errors import AppError  # noqa: E402
from core.base import ArtifactMissing, UseCaseError  # noqa: E402
from main import app  # noqa: E402

SERVICE = Path(__file__).resolve().parents[1]
DOMAIN_ERRORS = {
    "usecases.arbitrage.data": "ArbitrageDataError", "usecases.arbitrage.view": "ViewError",
    "usecases.aux_forecast.trainer": "AuxForecastError", "usecases.efficiency.models": "EfficiencyError",
    "usecases.fault_diag.data": "FaultDataError", "usecases.fault_diag.run": "FaultDiagError",
    "usecases.heatload.data": "HeatLoadError", "usecases.hvac_cop.model": "HvacCopError",
    "usecases.loss.data": "LossDataError", "usecases.mv_anomaly.features": "FeatureError",
    "usecases.mv_anomaly.trainer": "MvAnomalyError", "usecases.netload_forecast.models.base": "ForecastError",
    "usecases.price_forecast.models.base": "ForecastError", "usecases.rul.trainer": "RulError",
    "usecases.soc_estimation.trainer": "SocEstimationError", "usecases.soc_forecast.trainer": "SocForecastError",
    "usecases.thermal_forecast.trainer": "ThermalForecastError", "usecases.weak_module.models.base": "DetectionError",
    "core.base": "TrainingError",
}
LEAKS = ("Traceback", "KeyError", "C:\\", "secret", "artifacts")


def _token() -> str:
    t, _ = create_access_token(user_id="00000000-0000-0000-0000-0000000000ab", email="pytest.ml.errors@bess.local",
                               name="ADMIN", role="ADMIN", role_name="ADMIN",
                               perms=["ml.results:read", "ml.run:read", "ml.run:execute", "ml.run:delete",
                                      "ml.model:approve"], tenant_id=None, must_change_password=False, is_service=False)
    return t


@pytest.fixture(scope="module")
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture()
def rul(monkeypatch):
    """The RUL router with a fake store: start_run -> 990001, fail_run records its text."""
    router = importlib.import_module("usecases.rul.router")
    failed: list[str] = []
    monkeypatch.setattr(router.store, "start_run", lambda engine, info: 990001)
    monkeypatch.setattr(router.store, "fail_run", lambda engine, run_id, msg: failed.append(msg))
    return router, failed


def _post(client):
    return client.post("/rul/runs", json={"run_name": "pytest"}, headers={"Authorization": f"Bearer {_token()}",
                                                                          "X-Request-ID": "pytest-ml-err-0001"})


def test_every_use_case_error_is_a_400_app_error():
    for module, name in DOMAIN_ERRORS.items():
        cls = getattr(importlib.import_module(module), name)
        assert issubclass(cls, UseCaseError) and issubclass(cls, AppError), name
        err = cls("Only 3 units have data")
        assert (err.status, err.public, str(err)) == (400, "Only 3 units have data", "Only 3 units have data")


def test_expected_training_error_is_400_with_run_id(client, rul, monkeypatch):
    router, failed = rul
    def train(engine, cfg):
        raise router.T.RulError("Only 3 units have capacity tests; at least 5 are needed")
    monkeypatch.setattr(router.T, "train", train)
    r = _post(client)
    assert r.status_code == 400, r.text
    body = r.json()
    assert body["error"]["code"] == "RUL_INPUT_REJECTED" and body["error"]["context"] == {"run_id": 990001}
    assert body["detail"] == {"message": "Only 3 units have capacity tests; at least 5 are needed", "run_id": 990001}
    assert failed == ["Only 3 units have capacity tests; at least 5 are needed"]


def test_unexpected_training_error_is_generic_500_and_logged(client, rul, monkeypatch, caplog):
    router, failed = rul
    def train(engine, cfg):
        raise KeyError("secret column in C:\\bess\\artifacts\\runs\\x.pkl")
    monkeypatch.setattr(router.T, "train", train)
    with caplog.at_level(logging.ERROR, logger="bess.errors"):
        r = _post(client)
    assert r.status_code == 500, r.text
    body = r.json()
    assert body["error"]["code"] == "INTERNAL_ERROR" and body["error"]["context"] == {"run_id": 990001}
    assert body["detail"]["message"] == "An unexpected error occurred. Reference: pytest-ml-err-0001"
    for marker in LEAKS:
        assert marker not in r.text
    assert failed == ["Unexpected error (ref pytest-ml-err-0001)"]
    logged = [rec for rec in caplog.records if rec.name == "bess.errors" and rec.exc_info]
    assert logged and logged[0].exc_info[0] is KeyError  # the original stack trace reaches the log


def test_missing_model_file_hides_the_path():
    from core import registry
    with pytest.raises(ArtifactMissing) as info:
        registry.load_model({"run_id": 7, "artifact_path": "C:\\bess\\artifacts\\runs\\7.pkl", "model_type": "x"}, {})
    err = info.value
    assert err.status == 409 and "C:\\" not in err.public and "7.pkl" in (err.log_message or "")


def test_no_router_returns_exception_text():
    """Routers raise typed errors; the shared handlers build the response. Guards against a regression."""
    pattern = re.compile(r"detail=(str\(exc|f\"[^\"]*\{exc)|except Exception(?!.*noqa: BLE001 - )")
    offenders = [f"{p.relative_to(SERVICE)}:{n}" for p in (SERVICE / "usecases").glob("*/router.py")
                 for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1) if pattern.search(line)]
    assert offenders == []
