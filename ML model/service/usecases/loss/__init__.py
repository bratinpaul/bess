"""Loss decomposition / performance benchmarking: where the round trip goes (battery -> DC bus -> PCS -> transformer ->
POI, minus auxiliaries and standby) and whether each stage loses more than it should at the same operating conditions.

  data.py       time-aligned BMS / PCS / EMS / HVAC 5-min streams, master data, the OCV curve
  ledger.py     the per-interval energy balance: node powers, loss per stage, closure audits, self-discharge
  benchmark.py  expected loss per stage (grey-box models fitted on a baseline window), fixed vs variable split
  scorecard.py  daily / window roll-up: storage-corrected RTE at every node, factor chain, loss shares, expected chain,
                performance ratio, guarantee gap, loss value, EWMA / CUSUM control charts, loading curve
  run.py        one run over several battery systems (fleet benchmark)
  store.py      battery_ml.loss_run / loss_daily / loss_ledger (hypertable)
  router.py     the API (URL prefix /loss)
"""
from usecases.loss.router import PREFIX, USE_CASE as NAME, router, status

__all__ = ["NAME", "PREFIX", "router", "status"]
