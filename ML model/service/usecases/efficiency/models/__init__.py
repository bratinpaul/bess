"""The efficiency models: grey-box loss model (backbone), GAM, and the gradient boosting residual on the grey-box."""
from core.base import UseCaseError
from usecases.efficiency.models.gam import GamEfficiencyModel
from usecases.efficiency.models.greybox import GreyBoxLossModel, eta_from_loss, loss_from_eta
from usecases.efficiency.models.residual import BOOSTERS, ResidualBooster


class EfficiencyError(UseCaseError):
    """Bad training / estimation input (the API answers 400)."""
    code = "EFFICIENCY_INPUT_REJECTED"


def clean_params(specs: list[dict], params: dict, label: str) -> dict:
    """Defaults for missing values, types and ranges enforced (int / float / bool / choice)."""
    out = {}
    for spec in specs:
        value = params.get(spec["name"], spec["default"])
        if value in (None, ""):
            value = spec["default"]
        if spec["type"] == "bool":
            value = value if isinstance(value, bool) else str(value).lower() in ("1", "true", "yes", "on")
        elif spec["type"] == "choice":
            if value not in spec["choices"]:
                raise EfficiencyError(f"{label}: {spec['label']} must be one of {', '.join(spec['choices'])}")
        else:
            value = int(value) if spec["type"] == "int" else float(value)
            if not spec["min"] <= value <= spec["max"]:
                raise EfficiencyError(f"{label}: {spec['label']} must be between {spec['min']} and {spec['max']}")
        out[spec["name"]] = value
    unknown = set(params) - set(out)
    if unknown:
        raise EfficiencyError(f"Unknown parameter(s) for {label}: {', '.join(sorted(unknown))}")
    return out


__all__ = ["BOOSTERS", "EfficiencyError", "GamEfficiencyModel", "GreyBoxLossModel", "ResidualBooster", "clean_params",
           "eta_from_loss", "loss_from_eta"]
