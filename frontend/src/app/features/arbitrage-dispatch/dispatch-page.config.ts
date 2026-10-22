import { ArbRow, EnumSource, LookupSource } from '../../core/models/arbitrage.model';
import { TableColumn } from '../telemetry/table/table-column';

export type FieldKind = 'number' | 'int' | 'text' | 'datetime' | 'select';

/** One input of the add / edit dialog. `isKey` fields identify the row: set on add, read-only on edit. */
export interface FieldDef {
  key: string;
  label: string;
  kind: FieldKind;
  required?: boolean;
  isKey?: boolean;
  /** only on add (e.g. an optional explicit run_id) */
  createOnly?: boolean;
  from?: LookupSource;
  options?: EnumSource;
  step?: string;
  hint?: string;
}

export interface FilterDef {
  param: string;
  label: string;
  kind: 'select' | 'number';
  from?: LookupSource;
  options?: EnumSource;
}

export interface DispatchPageConfig {
  title: string;
  subtitle: string;
  endpoint: string;
  /** fields joined (in order) as the row's path key */
  keyFields: string[];
  columns: TableColumn[];
  defaultColumns: string[];
  /** ISO timestamp fields shown as plant-time labels in `<field>_label` columns */
  tsFields: string[];
  fields: FieldDef[];
  filters: FilterDef[];
  dateLabel: string;
  defaultOrder: 'asc' | 'desc';
  pageSizes: number[];
  fileName: string;
  uploadColumns: string;
  uploadNote: string;
  noun: string;
  deleteNote?: string;
  /** short description of a row for dialog titles */
  describe: (row: ArbRow, label: (iso: unknown) => string) => string;
  /** extra display-only values computed per row */
  derive?: (row: ArbRow) => ArbRow;
  /** default values of a new row (may look at the lookups / current filters) */
  defaults?: Record<string, unknown>;
}

const col = (key: string, label: string, group: string, kind: 'text' | 'number' = 'text', locked = false): TableColumn =>
  ({ key, label, kind, group, locked });

export const DISPATCH_PAGES: Record<string, DispatchPageConfig> = {
  'optimization-runs': {
    title: 'Optimization Run',
    subtitle: 'One row per optimizer run — horizon, method, objective, solver status and expected profit, with the schedule, state and realized outcome attached to it',
    endpoint: 'optimization-runs',
    keyFields: ['run_id'],
    columns: [
      col('run_id', 'Run', 'Run', 'number', true),
      col('system_code', 'System', 'Run'),
      col('issued_at_label', 'Issued At', 'Run'),
      col('horizon_start_label', 'Horizon Start', 'Run'),
      col('horizon_end_label', 'Horizon End', 'Run'),
      col('resolution_min', 'Resolution (min)', 'Run', 'number'),
      col('method', 'Method', 'Solver'),
      col('objective', 'Objective', 'Solver'),
      col('solver_status', 'Status', 'Solver'),
      col('solve_seconds', 'Solve (s)', 'Solver', 'number'),
      col('expected_profit_usd', 'Expected Profit (USD)', 'Result', 'number'),
      col('realized_net_usd', 'Realized Net (USD)', 'Result', 'number'),
      col('capture_pct', 'Realized / Expected (%)', 'Result', 'number'),
      col('schedule_rows', 'Schedule Rows', 'Linked', 'number'),
      col('has_state_label', 'Decision State', 'Linked'),
      col('outcome_intervals', 'Outcome Intervals', 'Linked', 'number')
    ],
    defaultColumns: ['run_id', 'system_code', 'issued_at_label', 'horizon_start_label', 'resolution_min', 'method',
      'objective', 'solver_status', 'expected_profit_usd', 'realized_net_usd', 'schedule_rows', 'has_state_label'],
    tsFields: ['issued_at', 'horizon_start', 'horizon_end'],
    fields: [
      { key: 'run_id', label: 'Run id (blank = next id)', kind: 'int', isKey: true, createOnly: true },
      { key: 'system_id', label: 'System', kind: 'select', from: 'systems', required: true, isKey: true },
      { key: 'issued_at', label: 'Issued at', kind: 'datetime', required: true },
      { key: 'horizon_start', label: 'Horizon start', kind: 'datetime', required: true },
      { key: 'horizon_end', label: 'Horizon end', kind: 'datetime', required: true },
      { key: 'resolution_min', label: 'Resolution (min)', kind: 'select', options: 'resolutions', required: true },
      { key: 'method', label: 'Method', kind: 'select', options: 'methods' },
      { key: 'objective', label: 'Objective', kind: 'select', options: 'objectives' },
      { key: 'solver_status', label: 'Solver status', kind: 'select', options: 'solver_statuses' },
      { key: 'expected_profit_usd', label: 'Expected profit (USD)', kind: 'number', step: '0.01' },
      { key: 'solve_seconds', label: 'Solve time (s)', kind: 'number', step: '0.001' }
    ],
    filters: [
      { param: 'system_id', label: 'System', kind: 'select', from: 'systems' },
      { param: 'solver_status', label: 'Solver status', kind: 'select', options: 'solver_statuses' }
    ],
    dateLabel: 'Horizon start',
    defaultOrder: 'desc',
    pageSizes: [25, 50, 100],
    fileName: 'optimization_run.csv',
    uploadColumns: 'run_id, system_code, issued_at, horizon_start, horizon_end, resolution_min, method, objective, solver_status, expected_profit_usd, solve_seconds',
    uploadNote: 'Load runs before their decision states, schedules and outcomes. A row with a run_id keeps it (an existing run is updated); a row without one gets the next id. system_code is the battery system name (e.g. EESL-BESS-S02; the pack files say BESS-01 and need that column changed). Checks: a known system, horizon end after start, issued at or before the horizon start, a whole number of resolution steps (5 / 15 / 30 / 60 min), known method / objective / status, and — for an existing run — that its schedule still fits the horizon.',
    noun: 'run',
    deleteNote: 'Its decision state and schedule rows are deleted with it; its outcome rows stay but lose the link to the run.',
    describe: (r, label) => `run ${r['run_id']} (${r['system_code']}, horizon ${label(r['horizon_start'])})`,
    derive: (r) => ({
      has_state_label: r['has_state'] ? 'Yes' : 'No',
      capture_pct:
        r['realized_net_usd'] != null && r['expected_profit_usd']
          ? +((100 * (r['realized_net_usd'] as number)) / (r['expected_profit_usd'] as number)).toFixed(1)
          : null
    }),
    defaults: { resolution_min: 60, method: 'MILP', objective: 'ARBITRAGE+AS', solver_status: 'OPTIMAL' }
  },

  'decision-states': {
    title: 'Decision State',
    subtitle: 'What the optimizer saw at horizon start for each run — SOC, SOH, usable energy, temperature, available power, cycle budget, aux forecast and AS reservation',
    endpoint: 'decision-states',
    keyFields: ['run_id'],
    columns: [
      col('run_id', 'Run', 'Run', 'number', true),
      col('system_code', 'System', 'Run'),
      col('issued_at_label', 'Issued At', 'Run'),
      col('horizon_start_label', 'Horizon Start', 'Run'),
      col('soc_start_pct', 'SOC Start (%)', 'Battery', 'number'),
      col('soh_pct', 'SOH (%)', 'Battery', 'number'),
      col('usable_energy_mwh', 'Usable Energy (MWh)', 'Battery', 'number'),
      col('avg_cell_temp_c', 'Avg Cell Temp (°C)', 'Battery', 'number'),
      col('p_charge_avail_kw', 'Charge Avail (kW)', 'Limits', 'number'),
      col('p_discharge_avail_kw', 'Discharge Avail (kW)', 'Limits', 'number'),
      col('cycles_used_today', 'Cycles Used Today', 'Limits', 'number'),
      col('aux_load_forecast_kw', 'Aux Forecast (kW)', 'Limits', 'number'),
      col('reserved_mw_as', 'AS Reserved (MW)', 'Limits', 'number')
    ],
    defaultColumns: ['run_id', 'system_code', 'horizon_start_label', 'soc_start_pct', 'soh_pct', 'usable_energy_mwh',
      'avg_cell_temp_c', 'p_charge_avail_kw', 'p_discharge_avail_kw', 'cycles_used_today', 'reserved_mw_as'],
    tsFields: ['issued_at', 'horizon_start'],
    fields: [
      { key: 'run_id', label: 'Run', kind: 'select', from: 'runs', required: true, isKey: true },
      { key: 'soc_start_pct', label: 'SOC at start (%)', kind: 'number', required: true, step: '0.1' },
      { key: 'soh_pct', label: 'SOH (%)', kind: 'number', step: '0.01' },
      { key: 'usable_energy_mwh', label: 'Usable energy (MWh)', kind: 'number', step: '0.001' },
      { key: 'avg_cell_temp_c', label: 'Avg cell temp (°C)', kind: 'number', step: '0.1' },
      { key: 'p_charge_avail_kw', label: 'Charge available (kW)', kind: 'number', step: '0.1' },
      { key: 'p_discharge_avail_kw', label: 'Discharge available (kW)', kind: 'number', step: '0.1' },
      { key: 'cycles_used_today', label: 'Cycles used today', kind: 'number', step: '0.01' },
      { key: 'aux_load_forecast_kw', label: 'Aux load forecast (kW)', kind: 'number', step: '0.1' },
      { key: 'reserved_mw_as', label: 'Reserved for AS (MW)', kind: 'number', step: '0.001' }
    ],
    filters: [
      { param: 'system_id', label: 'System', kind: 'select', from: 'systems' },
      { param: 'run_id', label: 'Run', kind: 'select', from: 'runs' }
    ],
    dateLabel: 'Horizon start',
    defaultOrder: 'desc',
    pageSizes: [25, 50, 100],
    fileName: 'decision_state.csv',
    uploadColumns: 'run_id, soc_start_pct, soh_pct, usable_energy_mwh, avg_cell_temp_c, p_charge_avail_kw, p_discharge_avail_kw, cycles_used_today, aux_load_forecast_kw, reserved_mw_as',
    uploadNote: 'One state per run; every run_id must already be loaded (Optimization Run first). An existing state is updated. Checks: SOC 0–100 %, SOH 0–110 %, cell temperature −40–90 °C, powers, energy, cycles and reservation ≥ 0.',
    noun: 'decision state',
    describe: (r, label) => `the state of run ${r['run_id']} (${r['system_code']}, horizon ${label(r['horizon_start'])})`
  },

  'dispatch-schedules': {
    title: 'Dispatch Schedule',
    subtitle: 'The optimizer’s setpoint per interval (+ discharge / − charge), SOC target, mode, market and the price it assumed — next to what was actually delivered',
    endpoint: 'dispatch-schedules',
    keyFields: ['run_id', 'interval_start'],
    columns: [
      col('interval_start_label', 'Interval Start', 'Interval', 'text', true),
      col('run_id', 'Run', 'Interval', 'number'),
      col('system_code', 'System', 'Interval'),
      col('resolution_min', 'Resolution (min)', 'Interval', 'number'),
      col('p_setpoint_kw', 'Setpoint (kW)', 'Schedule', 'number'),
      col('direction', 'Direction', 'Schedule'),
      col('soc_target_pct', 'SOC Target (%)', 'Schedule', 'number'),
      col('mode', 'Mode', 'Schedule'),
      col('market', 'Market', 'Schedule'),
      col('forecast_price_mwh', 'Assumed Price (USD/MWh)', 'Schedule', 'number'),
      col('actual_kw', 'Actual Avg (kW)', 'Outcome', 'number'),
      col('net_pnl_usd', 'Net P&L (USD)', 'Outcome', 'number')
    ],
    defaultColumns: ['interval_start_label', 'run_id', 'p_setpoint_kw', 'direction', 'soc_target_pct', 'mode', 'market',
      'forecast_price_mwh', 'actual_kw', 'net_pnl_usd'],
    tsFields: ['interval_start'],
    fields: [
      { key: 'run_id', label: 'Run', kind: 'select', from: 'runs', required: true, isKey: true },
      { key: 'interval_start', label: 'Interval start', kind: 'datetime', required: true, isKey: true,
        hint: 'inside the run’s horizon, on its resolution grid' },
      { key: 'p_setpoint_kw', label: 'Setpoint (kW, + discharge / − charge)', kind: 'number', required: true, step: '0.1' },
      { key: 'soc_target_pct', label: 'SOC target (%)', kind: 'number', step: '0.1' },
      { key: 'mode', label: 'Mode', kind: 'select', options: 'modes' },
      { key: 'market', label: 'Market', kind: 'select', options: 'markets' },
      { key: 'forecast_price_mwh', label: 'Assumed price (USD/MWh)', kind: 'number', step: '0.01' }
    ],
    filters: [
      { param: 'run_id', label: 'Run', kind: 'select', from: 'runs' },
      { param: 'system_id', label: 'System', kind: 'select', from: 'systems' },
      { param: 'mode', label: 'Mode', kind: 'select', options: 'modes' },
      { param: 'market', label: 'Market', kind: 'select', options: 'markets' }
    ],
    dateLabel: 'Interval',
    defaultOrder: 'asc',
    pageSizes: [24, 48, 96, 168],
    fileName: 'dispatch_schedule.csv',
    uploadColumns: 'run_id, interval_start, p_setpoint_kw, soc_target_pct, mode, market, forecast_price_mwh',
    uploadNote: 'Every run_id must already be loaded, and every interval must lie inside its run’s horizon on the run’s resolution grid. Existing (run, interval) rows are updated. Checks: setpoint within ±100 MW, SOC target 0–100 %, a known mode (the telemetry dispatch modes) and market (DAM / RT / AS). Runs whose horizon is not fully covered are reported.',
    noun: 'interval',
    describe: (r, label) => `run ${r['run_id']} · ${label(r['interval_start'])}`,
    derive: (r) => {
      const p = r['p_setpoint_kw'] as number;
      return { direction: p > 0.5 ? 'Discharge' : p < -0.5 ? 'Charge' : 'Idle' };
    }
  },

  'dispatch-outcomes': {
    title: 'Dispatch Outcome',
    subtitle: 'Realized result per interval — scheduled vs actual power, settlement price, delivered energy and revenue net of degradation and grid cost',
    endpoint: 'dispatch-outcomes',
    keyFields: ['system_id', 'interval_start'],
    columns: [
      col('interval_start_label', 'Interval Start', 'Interval', 'text', true),
      col('system_code', 'System', 'Interval'),
      col('run_id', 'Run', 'Interval', 'number'),
      col('p_scheduled_kw', 'Scheduled (kW)', 'Power', 'number'),
      col('p_actual_kw', 'Actual (kW)', 'Power', 'number'),
      col('deviation_kw', 'Actual − Scheduled (kW)', 'Power', 'number'),
      col('price_mwh', 'Price (USD/MWh)', 'Settlement', 'number'),
      col('energy_mwh', 'Energy (MWh)', 'Settlement', 'number'),
      col('gross_revenue_usd', 'Gross (USD)', 'P&L', 'number'),
      col('degradation_cost_usd', 'Degradation (USD)', 'P&L', 'number'),
      col('grid_cost_usd', 'Grid Cost (USD)', 'P&L', 'number'),
      col('net_pnl_usd', 'Net P&L (USD)', 'P&L', 'number')
    ],
    defaultColumns: ['interval_start_label', 'run_id', 'p_scheduled_kw', 'p_actual_kw', 'deviation_kw', 'price_mwh',
      'energy_mwh', 'gross_revenue_usd', 'degradation_cost_usd', 'grid_cost_usd', 'net_pnl_usd'],
    tsFields: ['interval_start'],
    fields: [
      { key: 'system_id', label: 'System', kind: 'select', from: 'systems', required: true, isKey: true },
      { key: 'interval_start', label: 'Interval start', kind: 'datetime', required: true, isKey: true },
      { key: 'run_id', label: 'Run (optional)', kind: 'select', from: 'runs' },
      { key: 'p_scheduled_kw', label: 'Scheduled (kW)', kind: 'number', step: '0.1' },
      { key: 'p_actual_kw', label: 'Actual (kW)', kind: 'number', step: '0.1' },
      { key: 'price_mwh', label: 'Price (USD/MWh)', kind: 'number', step: '0.01' },
      { key: 'energy_mwh', label: 'Energy (MWh, signed)', kind: 'number', step: '0.000001' },
      { key: 'gross_revenue_usd', label: 'Gross revenue (USD)', kind: 'number', step: '0.0001', hint: 'blank = price × energy' },
      { key: 'degradation_cost_usd', label: 'Degradation cost (USD)', kind: 'number', step: '0.0001' },
      { key: 'grid_cost_usd', label: 'Grid cost (USD)', kind: 'number', step: '0.0001' },
      { key: 'net_pnl_usd', label: 'Net P&L (USD)', kind: 'number', step: '0.0001', hint: 'blank = gross − degradation − grid' }
    ],
    filters: [
      { param: 'system_id', label: 'System', kind: 'select', from: 'systems' },
      { param: 'run_id', label: 'Run', kind: 'select', from: 'runs' }
    ],
    dateLabel: 'Interval',
    defaultOrder: 'asc',
    pageSizes: [48, 96, 192, 384],
    fileName: 'dispatch_outcome.csv',
    uploadColumns: 'system_code, interval_start, run_id, p_scheduled_kw, p_actual_kw, price_mwh, energy_mwh, gross_revenue_usd, degradation_cost_usd, grid_cost_usd, net_pnl_usd',
    uploadNote: 'Existing (system, interval) rows are updated. system_code is the battery system name (e.g. EESL-BESS-S02; the pack files say BESS-01 and need that column changed). Checks: a known system; a run_id (when given) that exists and whose horizon holds the interval; gross = price × energy and net = gross − degradation − grid within 1 cent — derived when empty, refused when they contradict; costs ≥ 0.',
    noun: 'outcome',
    describe: (r, label) => `${r['system_code']} · ${label(r['interval_start'])}`
  },

  'as-awards': {
    title: 'AS Award',
    subtitle: 'Committed ancillary-service capacity per system, product and delivery window — each award reserves power / SOC headroom the optimizer must respect',
    endpoint: 'as-awards',
    keyFields: ['award_id'],
    columns: [
      col('award_id', 'Award', 'Award', 'number', true),
      col('delivery_start_label', 'Delivery Start', 'Award'),
      col('delivery_end_label', 'Delivery End', 'Award'),
      col('duration_min', 'Duration (min)', 'Award', 'number'),
      col('system_code', 'System', 'Award'),
      col('product_code', 'Product', 'Award'),
      col('awarded_mw', 'Awarded (MW)', 'Commitment', 'number'),
      col('capacity_price_mw', 'Capacity Price (USD/MW)', 'Commitment', 'number'),
      col('revenue_usd', 'Revenue (USD)', 'Commitment', 'number')
    ],
    defaultColumns: ['award_id', 'delivery_start_label', 'delivery_end_label', 'duration_min', 'system_code', 'product_code',
      'awarded_mw', 'capacity_price_mw', 'revenue_usd'],
    tsFields: ['delivery_start', 'delivery_end'],
    fields: [
      { key: 'system_id', label: 'System', kind: 'select', from: 'systems', required: true, isKey: true },
      { key: 'product_id', label: 'AS product', kind: 'select', from: 'products', required: true, isKey: true },
      { key: 'delivery_start', label: 'Delivery start', kind: 'datetime', required: true, isKey: true },
      { key: 'delivery_end', label: 'Delivery end', kind: 'datetime', required: true },
      { key: 'awarded_mw', label: 'Awarded (MW)', kind: 'number', required: true, step: '0.001' },
      { key: 'capacity_price_mw', label: 'Capacity price (USD/MW)', kind: 'number', step: '0.01' },
      { key: 'revenue_usd', label: 'Revenue (USD)', kind: 'number', step: '0.01', hint: 'blank = MW × price × hours' }
    ],
    filters: [
      { param: 'system_id', label: 'System', kind: 'select', from: 'systems' },
      { param: 'product_id', label: 'Product', kind: 'select', from: 'products' }
    ],
    dateLabel: 'Delivery start',
    defaultOrder: 'asc',
    pageSizes: [25, 50, 100, 200],
    fileName: 'as_award.csv',
    uploadColumns: 'system_code, product_code, delivery_start, delivery_end, awarded_mw, capacity_price_mw, revenue_usd',
    uploadNote: 'An award for the same system, product and delivery start is updated, not duplicated. system_code is the battery system name (e.g. EESL-BESS-S02; the pack files say BESS-01 and need that column changed). Checks: a known system and product, delivery end after start (at most a week), awarded MW above zero and at least the product’s minimum bid, prices and revenue ≥ 0; revenue is derived (MW × price × hours) when empty. Overlapping windows for the same system and product are reported.',
    noun: 'award',
    describe: (r, label) => `award ${r['award_id']} (${r['product_code']} · ${r['system_code']} · ${label(r['delivery_start'])})`
  },

  'price-scenarios': {
    title: 'Price Scenario',
    subtitle: 'Sampled price paths with weights for stochastic / robust dispatch — per node, issue vintage, scenario and target hour, next to the P50 forecast and the realized DAM price',
    endpoint: 'price-scenarios',
    keyFields: ['node_id', 'issued_at', 'scenario_id', 'target_ts'],
    columns: [
      col('target_ts_label', 'Target Hour', 'Scenario', 'text', true),
      col('issued_at_label', 'Issued At', 'Scenario'),
      col('horizon_h', 'Horizon (h)', 'Scenario', 'number'),
      col('node_code', 'Node', 'Scenario'),
      col('scenario_id', 'Scenario', 'Scenario', 'number'),
      col('price_mwh', 'Price (USD/MWh)', 'Path', 'number'),
      col('probability', 'Weight', 'Path', 'number'),
      col('forecast_p50', 'Forecast P50', 'Context', 'number'),
      col('actual_mwh', 'Actual DAM', 'Context', 'number'),
      col('vs_actual', 'Scenario − Actual', 'Context', 'number')
    ],
    defaultColumns: ['target_ts_label', 'issued_at_label', 'scenario_id', 'price_mwh', 'probability', 'forecast_p50',
      'actual_mwh'],
    tsFields: ['target_ts', 'issued_at'],
    fields: [
      { key: 'node_id', label: 'Price node', kind: 'select', from: 'nodes', required: true, isKey: true },
      { key: 'issued_at', label: 'Issued at', kind: 'datetime', required: true, isKey: true },
      { key: 'scenario_id', label: 'Scenario id', kind: 'int', required: true, isKey: true },
      { key: 'target_ts', label: 'Target hour', kind: 'datetime', required: true, isKey: true },
      { key: 'price_mwh', label: 'Price (USD/MWh)', kind: 'number', required: true, step: '0.01' },
      { key: 'probability', label: 'Weight (0–1)', kind: 'number', step: '0.0001', hint: 'weights of one hour should sum to 1' }
    ],
    filters: [
      { param: 'node_id', label: 'Node', kind: 'select', from: 'nodes' },
      { param: 'issued_at', label: 'Issue vintage', kind: 'select', from: 'scenario_vintages' },
      { param: 'scenario_id', label: 'Scenario id', kind: 'number' }
    ],
    dateLabel: 'Target',
    defaultOrder: 'asc',
    pageSizes: [50, 100, 240, 500],
    fileName: 'price_scenario.csv',
    uploadColumns: 'node_code, issued_at, scenario_id, target_ts, price_mwh, probability',
    uploadNote: 'Existing (node, vintage, scenario, hour) rows are updated. Checks: a known price node, target after the issue time, scenario id ≥ 1, price −1000–20000 USD/MWh, weight 0–1. Hours whose weights in the file do not sum to 1 (±0.01) are reported.',
    noun: 'scenario',
    describe: (r, label) => `scenario ${r['scenario_id']} · ${label(r['target_ts'])} (issued ${label(r['issued_at'])})`,
    derive: (r) => ({
      vs_actual: r['actual_mwh'] == null ? null : +((r['price_mwh'] as number) - (r['actual_mwh'] as number)).toFixed(2)
    })
  }
};
