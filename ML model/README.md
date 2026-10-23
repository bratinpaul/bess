# BESS ML service

FastAPI service on port 8100 (run from `service/` with the project `.venv`):

```
cd "ML model/service"
..\..\.venv\Scripts\python -m uvicorn main:app --port 8100 --no-server-header
```

## Layout

```
service/
  main.py                 app, CORS, /health; mounts every use case under /<name>
  core/                   shared by all use cases
    db.py                 SQLAlchemy engine (plant time Asia/Kolkata)
    metrics.py            regression scores, importance shares, permutation importance
    base.py               BaseRegressor (one algorithm) and BaseTrainer (the shared training flow)
    registry.py           battery_ml.model_run / model_run_curve, model files, default run per use case
  usecases/
    __init__.py           USE_CASES - the list main.py mounts
    soh/                  SOH estimation (URL prefix /soh, model_run.use_case = 'soh')
      features.py         dataset: BMS + module telemetry -> feature rows per time bucket
      models/             xgboost_model.py, lightgbm_model.py (BaseRegressor subclasses), MODELS registry
      trainer.py          SohTrainer(BaseTrainer): target soh_pct, SOH data warnings
      schemas.py          request / response bodies
      router.py           /models /model-info /predict /sample /train/options /train/preview /train /runs...
    weak_module/          weak module detection (URL prefix /weak-module, tables battery_ml.anomaly_*)
      features.py         module_telemetry -> module-day/hour rows: V/T deviation vs system and vs pack, imbalance,
                          deviation under load, balancing
      models/             base.py (BaseDetector), isolation_forest.py, dbscan.py (auto eps from the k-distance knee,
                          auto min_samples = 2 x rows per module)
      detector.py         both models -> per-module verdict (WEAK = both, SUSPECT = one), combined score, reasons
      store.py            anomaly_run / anomaly_module_result / anomaly_point, model files in artifacts/anomaly
      router.py           /options /preview /runs /runs/{id}/score /runs/{id}/points /runs/{id}/modules/{m}/series
    efficiency/           PCS conversion + round-trip efficiency (URL prefix /efficiency, tables battery_ml.efficiency_*)
      features.py         pcs_telemetry + pcs master -> operating points (load fraction, direction, |S|, PF, DC voltage,
                          temperatures, AC voltage / frequency, grid service, age); target efficiency_pct
      models/             greybox.py (P_loss = a + b·I + c·I², bounded WLS), gam.py (additive splines + ridge),
                          residual.py (LightGBM / XGBoost on the grey-box residual, TreeSHAP)
      cycles.py           cycles per PCS -> measured DC / AC / system RTE (BMS / PCS / EMS counters, aux + HVAC);
                          Ridge regression of the DC RTE on cycle features
      trainer.py          one run: the three models on one split, scores, health (a / b / c, weekly loss index),
                          curves along each unit's operating profile, composed cycle RTE
      estimator.py        one operating point (η per model, loss breakdown, SHAP) and one cycle (DC / AC / system RTE)
      store.py / router.py  /options /preview /runs /runs/{id}/cycles /scores /models /model-info /sample /predict /cycle
    price_forecast/       electricity-price forecast P10/P50/P90, 1-48 h ahead (URL prefix /price-forecast,
                          tables battery_ml.price_forecast_*, TOU bands battery_master.ems_tariff_period)
      features.py         ems_telemetry -> hourly price / spike / frequency-stress series; direct multi-horizon rows
      models/             baselines.py (seasonal naïve, SARIMA - statsmodels), gbm.py (LightGBM / XGBoost: anchored on
                          the same hour yesterday, Huber P50 + quantile P10/P90, conformal calibration), nbeats.py
                          (N-BEATS-style MLP, scikit-learn), spike.py (spike classifier + regressors)
      trainer.py          split per EMS in time, backtest on common origins, scores, live forecast
      store.py / router.py  /options /preview /runs /runs/{id}/origins /runs/{id}/backtest /scores /models /forecast
    soc_forecast/         SOC trajectory P10/P50/P90, 5-min steps, up to 24 h ahead (URL prefix /soc-forecast,
                          tables battery_ml.soc_forecast_*)
      features.py         ems / system / hvac telemetry -> 5-min series; dispatch_event schedule; typical-day setpoint;
                          coulomb-counting physics (%/kWh charge / discharge, SOC limits) fitted per EMS
      trainer.py          plans per origin, physics roll-forward, LightGBM quantile residual models per plan source,
                          backtest (hold / physics / hybrid x typical / scheduled), live forecast (schedule, typical
                          day or what-if blocks) with available energy, headroom and time to limits
      store.py / router.py  /options /runs /runs/{id}/origins /runs/{id}/backtest /models /forecast (POST)
    thermal_forecast/     cell max / coolant return / IGBT / enclosure temperature 5-60 min ahead, P10/P50/P90 per asset
                          (URL prefix /thermal-forecast, tables battery_ml.thermal_forecast_*)
      features.py         battery_telemetry.v_thermal_features (5-min join of the BMS / PCS / HVAC / EMS hypertables + the
                          rolling 1 h features of the *_thermal_15m continuous aggregates), input guards, target specs
      physics.py          grey-box first-order RC per target and asset (steady state + exponential approach, tau fitted)
      trainer.py          direct multi-horizon rows, LightGBM quantile models on the RC residual, persistence and seasonal
                          baselines, scores incl. threshold-exceedance recall, online and stateless (vector) predict
      store.py / router.py  /options /runs /runs/{id}/series /models /predict /predict/vector
    netload_forecast/     site net load (gross − behind-the-meter PV) P10/P50/P90 every 5 min up to 48 h, and the daily
                          billing-window peak: size, time, exceedance of a threshold (URL prefix /netload-forecast,
                          tables battery_ml.netload_forecast_*)
      features.py         demand_telemetry 5-min series; weather_actual + weather_forecast runs (as known at the origin,
                          fallback to recent measured days); calendar_day (workday / holiday); demand_tariff window;
                          direct multi-horizon rows (history incl. same-slot of the last same-type days, calendar,
                          weather, BTM)
      models/             baselines.py (seasonal naïve on the same day type, SARIMAX hourly with workday + weather),
                          gbm.py (LightGBM anchored on the same-type-day profile, Huber P50 + quantile P10/P90, CQR),
                          nbeats.py (N-BEATS-style hourly MLP with future covariates), peak.py (daily peak from a path,
                          held-out peak calibration, logistic peak-exceedance classifier)
      trainer.py          split per metering point, backtest on common origins, load + peak scores, live forecast
      store.py / router.py  /options /preview /runs /runs/{id}/origins /runs/{id}/backtest /runs/{id}/peaks /models
                          /forecast
    aux_forecast/         site parasitic draw aux_load_kw (= HVAC + controls, always positive) P10/P50/P90 every 5 min,
                          5 min - 24 h ahead, + aux energy per interval / day (URL prefix /aux-forecast, tables
                          battery_ml.aux_forecast_*)
      features.py         battery_telemetry.v_aux_features (5-min join of EMS / HVAC / BMS / PCS + rolling features of the
                          ems_aux_15m / hvac_thermal_15m continuous aggregates), input guards, ambient as known at the
                          origin (weather_forecast run offset to the HVAC sensor, else the daily profile)
      physics.py          grey-box per site: controls + p0 + (battery heat + envelope + solar) / COP(ambient)
      trainer.py          direct multi-horizon rows (sampled steps in training, every step in test), pooled LightGBM
                          quantile models on the grey-box residual, persistence / same-time-yesterday baselines, scores
                          per horizon bucket + daily aux kWh (23:55 issues), online (as_of) and stateless (vector) predict
      store.py / router.py  /options /runs /runs/{id}/origins /runs/{id}/trajectory /runs/{id}/series /runs/{id}/daily
                          /models /predict /predict/vector
    rul/                  remaining useful life (days / EFC to EOL, P10/P50/P90) per RUL fleet unit; EOL from
                          battery_master.eol_criteria (URL prefix /rul, tables battery_ml.rul_*)
      features.py         battery_master.v_rul_training + capacity_test (RPT) + lifecycle_event + eol_criteria; landmark
                          survival targets (censored units: known-alive time)
      physics.py          fade curve per chemistry: sqrt-t calendar + EFC power law + Arrhenius, batch / shrunk unit
                          factors (RPT-weighted), SOH-band knee; projected to the capacity / resistance EOL
      survival.py         Cox PH (ridge Newton, Breslow) and a Random Survival Forest, in numpy
      trainer.py          leave-one-unit-out backtest of physics / LightGBM / hybrid / Cox / RSF, band calibration,
                          censoring-aware scores (MAE, coverage, C-index, censored violations, oracle), forecasts, what-if
      store.py / router.py  /options /runs /runs/{id}/forecasts /runs/{id}/backtest /models /predict
    mv_anomaly/           multivariate anomaly detection per battery system: BMS / PCS / HVAC / EMS jointly, one row per
                          5-min interval (URL prefix /mv-anomaly, tables battery_ml.mv_anomaly_run / mv_anomaly_score
                          (hypertable) / view v_mv_anomaly_alarm)
      features.py         time_bucket join of the four hypertables, derived signals (ΔV, ΔT, PCS loss, setpoint and
                          dispatch error), residuals fitted on clean rows (ΔV | SOC band + regime, cell T | I²R load,
                          IGBT | |S|), regime / SOC band, frozen + missing sensor rules, alarm labels, training exclusions
      models.py           PCA (Q / T²), Isolation Forest, Elliptic Envelope, dense and windowed autoencoders (sklearn MLP;
                          no torch) - each returns a score and per-feature contributions
      trainer.py          chronological split, known-good rows, regime as features or one model per regime, percentile
                          limits (optionally tuned on training-window alarms), smoothing + debounce, evaluation vs
                          alarm_event, attribution, episodes, scoring other windows + drift warnings (SOH, ambient)
      store.py / router.py  /options /preview /runs /runs/{id}/score /live/score /runs/{id}/timeline /episodes /alarms
                          /contributors /signals
      batch.py            micro-batch: every system's live model scores the newest telemetry (for a scheduled task)
    arbitrage/            energy-arbitrage / dispatch optimization (URL prefix /arbitrage, tables battery_ml.arb_study /
                          arb_study_day / arb_backtest + the decision chain optimization_run.study_id -> decision_state ->
                          dispatch_schedule); no model files
      data.py             inputs from the arbitrage data pack tables (battery_opt_param, efficiency / degradation curves,
                          interconnection_limit, grid_charge, as_price / as_award, decision_state, price_forecast /
                          price_scenario, rt / dam prices, dispatch_outcome)
      optimizer.py        MILP on scipy.optimize.milp (HiGHS, no extra package): split / segmented efficiency, DoD-layer
                          degradation, FREQ_REG capacity stacking (headroom, min bid, cap, award floors), ramp, POI,
                          cycle cap, terminal SOC; deterministic (P50) or two-stage stochastic over scenarios + CVaR
      backtest.py         a study: receding horizon day by day, hourly plan executed at 15-min rt_price, perfect-foresight
                          oracle, sanity checks (SOC band, no simultaneous charge, losses, cycle cap, ≤ oracle, deg = 0
                          over-cycles, pack P&L reproduced)
      store.py / view.py / router.py  /options /studies /studies/{id} /days /day (Dispatch Viewer read model)
artifacts/runs/           model files, run_<id>_<model_type>.<ext>
artifacts/mv_anomaly/     multivariate anomaly model files (joblib: preprocessor, residual fits, detectors, limits)
artifacts/rul/            RUL run files (joblib: per-chemistry physics, quantile and survival models)
artifacts/aux_forecast/   aux forecast run files (joblib: per-site grey-box registry, residual quantile models, profiles)
artifacts/netload_forecast/ net-load run files (joblib: fitted forecasters, peak calibration, classifier, PV ratio)
artifacts/thermal_forecast/ thermal run files (joblib: per-asset RC registry, per-target quantile models, profiles)
artifacts/soc_forecast/   SOC forecast run files (joblib: physics per EMS, typical days, residual models)
artifacts/price_forecast/ price forecast run files (joblib: every fitted forecaster)
artifacts/efficiency/     efficiency run files (joblib: grey-box, GAM, booster, profiles, DC RTE regression)
```

The SOH endpoints are also served without the `/soh` prefix (`/predict`, `/train`, `/runs`, ...) for older
callers; new code uses `/soh/...`. The estimator's `?model=active` is the run made default on Model Training,
else the latest completed run.

## Adding a use case

1. **Package** - create `service/usecases/<name>/` with `__init__.py` exporting `NAME`, `router` and `status()`
   (and optionally `PREFIX` for the URL, e.g. `weak-module`; see `usecases/soh/__init__.py`), and add it to
   `USE_CASES` in `usecases/__init__.py`. Its API appears under `/<PREFIX or NAME>/...`.
2. **Features** - `features.py` builds the training rows: a DataFrame with a `ts` column, the target column and
   the feature columns. Keep SQL and feature definitions here.
3. **Models** - one class per algorithm in `models/`. Regression use cases subclass `core.base.BaseRegressor`
   (unsupervised ones define their own interface, like `weak_module/models/base.py`): set `key`, `label`,
   `file_suffix`, `param_specs`, and implement `fit` (return a `FitReport` with the per-round curve), `predict`,
   `gain_importance`, `estimator`, `save` and `load`. Collect them in `models/__init__.py` as
   `MODELS = {cls.key: cls}`. Reuse the SOH classes as a template; the algorithm code is kept per use case so
   each can tune its own parameter ranges.
4. **Trainer** - subclass `core.base.BaseTrainer`, set `target` and `models`, and override `data_warnings`
   for checks specific to the use case. Split, feature selection, scoring and predictions come from the base.
5. **Schemas and router** - request / response models in `schemas.py`; endpoints in `router.py` using
   `core.registry` with the use case's `NAME` (every registry call takes it, so runs, the default run and
   the model files stay separate per use case).
6. **Database** - runs go into `battery_ml.model_run` with `use_case = NAME`. The table's CHECK constraints
   allow model types `xgboost` / `lightgbm` and grains `5min` / `hour` / `day`; widen them with an `ALTER TABLE`
   on the database (and regenerate the DDL with `db_docs/generate_ddl.py`) if the new use case needs others.
7. **Frontend** - add a service pointing at `http://localhost:8100/<name>` and the pages under `features/ml/`.
