"""ML use cases: one package per business use case, each with its own features, models, trainer, schemas and
router (see "ML model/README.md" for how to add one). main.py mounts every router in USE_CASES under /<PREFIX> (default: /<NAME>)."""
from usecases import arbitrage, aux_forecast, efficiency, fault_diag, heatload, hvac_cop, loss, mv_anomaly, rul, netload_forecast, price_forecast, soc_estimation, soc_forecast, soh, thermal_forecast, weak_module

USE_CASES = [soh, weak_module, efficiency, price_forecast, soc_forecast, thermal_forecast, netload_forecast, aux_forecast, rul, soc_estimation, mv_anomaly, arbitrage, loss, heatload, hvac_cop, fault_diag]
