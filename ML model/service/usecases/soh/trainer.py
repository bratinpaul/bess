"""SOH trainer: the shared regression training flow (core.base.BaseTrainer) on the SOH target, with SOH warnings.

Note: tree models can't predict below the lowest SOH they were trained on. With a steadily falling SOH a
chronological test therefore tends to score low; LightGBM's linear_tree fits a line in each leaf and can
follow the trend.
"""
import numpy as np
import pandas as pd

from core.base import BaseRegressor, BaseTrainer
from usecases.soh.features import TARGET
from usecases.soh.models import MODELS


class SohTrainer(BaseTrainer):
    target = TARGET
    models = MODELS
    # rows are per battery system: chronological split and test scores per plant
    group_col = "system_id"

    def data_warnings(self, df: pd.DataFrame, y_train: np.ndarray, y_test: np.ndarray, split_method: str,
                      model: BaseRegressor) -> list[str]:
        warnings = []
        std = df[TARGET].std()
        if std < 0.01:
            warnings.append(f"SOH hardly varies in the selected rows (std {std:.4f} points): scores such as R² say "
                            "little - widen the date range or turn off 'only rows with module data'")
        if split_method == "chronological" and y_test.min() < y_train.min() - 1e-9 and not model.extrapolates:
            warnings.append("The test period reaches lower SOH than the training period; tree models can't predict below "
                            "what they were trained on (try LightGBM with linear trees)")
        return warnings


trainer = SohTrainer()
