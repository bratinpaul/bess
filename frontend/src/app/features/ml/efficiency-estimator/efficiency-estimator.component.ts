import { CommonModule } from '@angular/common';
import { Component, OnInit, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { AuthService } from '../../../core/auth/auth.service';

import {
  EffCycleIn,
  EffCycleResult,
  EffDirection,
  EffModelInfo,
  EffModelKey,
  EffModelOption,
  EffPointIn,
  EffPointResult,
  GridService
} from '../../../core/models/efficiency.model';
import { EfficiencyService } from '../../../core/services/efficiency.service';
import { ChartCanvasComponent } from '../../telemetry/graphs/chart-canvas.component';
import { AnyConfig, MODEL_COLORS, MODEL_KEYS, MODEL_LABELS, curveChart, fmtNum, fmtPct, hbar } from '../efficiency-shared/eff-charts';

const WHAT_IF_TRAINERS_ONLY = 'What-if predictions are limited to model trainers (Admin, Data Scientist).';

type Unit = EffModelInfo['units'][number];

/* Loss colours (validated as a 3-slot set): PCS (charge and discharge), battery, auxiliaries. */
const LOSS_COLORS = { pcs: '#2a78d6', battery: '#2aa198', aux: '#d9480f' };
// grey-box terms share the model's blue (the bars are labelled); the boosting correction is the hybrid's orange
const BREAKDOWN_COLORS = ['#2a78d6', '#2a78d6', '#2a78d6', '#d9480f'];
const POS = '#d9480f';
const NEG = '#2a78d6';

/** Insights -> Efficiency & performance -> Efficiency Estimator: PCS conversion efficiency at an operating point,
 *  and the DC / AC / system round-trip of a charge-discharge cycle. */
@Component({
  selector: 'app-efficiency-estimator',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink, ChartCanvasComponent],
  templateUrl: './efficiency-estimator.component.html',
  styleUrls: ['../soh-estimator/soh-estimator.component.scss', './efficiency-estimator.component.scss']
})
export class EfficiencyEstimatorComponent implements OnInit {
  private auth = inject(AuthService);
  readonly modelKeys = MODEL_KEYS;
  readonly modelLabels = MODEL_LABELS;
  readonly modelColors = MODEL_COLORS;
  readonly gridServices: GridService[] = ['NONE', 'FREQ_WATT', 'VOLT_VAR'];
  fmtPct = fmtPct;
  fmtNum = fmtNum;

  models: EffModelOption[] = [];
  modelsLoaded = false;
  modelsError: string | null = null;
  modelKey = 'active';
  info: EffModelInfo | null = null;
  infoError: string | null = null;
  pcsId: number | null = null;
  tab: 'point' | 'cycle' = 'point';

  // operating point
  point: EffPointIn = this.blankPoint(0);
  pointSource: string | null = null;
  measuredEta: number | null = null;
  predicting = false;
  pointError: string | null = null;
  pointResult: EffPointResult | null = null;
  pointCurve?: AnyConfig;
  shapChart?: AnyConfig;
  shapHeight = 220;
  breakdownChart?: AnyConfig;
  loadingSample = false;

  // cycle
  cycle: EffCycleIn = this.blankCycle(0);
  cycling = false;
  cycleError: string | null = null;
  cycleResult: EffCycleResult | null = null;
  lossChart?: AnyConfig;

  constructor(private service: EfficiencyService, private route: ActivatedRoute, private router: Router) {}

  ngOnInit(): void {
    const q = this.route.snapshot.queryParamMap;
    this.service.models().subscribe({
      next: (models) => {
        this.models = models;
        this.modelsLoaded = true;
        const wanted = q.get('model');
        this.modelKey = wanted && models.some((m) => String(m.run_id) === wanted) ? wanted : 'active';
        if (models.length) {
          this.loadInfo();
        }
      },
      error: (err) => {
        this.modelsLoaded = true;
        this.modelsError = err?.status === 0 ? 'Could not reach the ML service. Is it running on port 8100?' : 'Could not load the models.';
      }
    });
  }

  // ---------------------------------------------------------------- model / unit

  optionLabel(m: EffModelOption): string {
    const rmse = m.metrics?.hybrid?.test?.rmse;
    return `#${m.run_id}${m.run_name ? ' ' + m.run_name : ''}${m.is_default ? ' (default)' : ''} · ${m.pcs_ids.length} PCS · hybrid RMSE ${
      rmse === null || rmse === undefined ? '—' : rmse.toFixed(3) + ' pp'
    }`;
  }

  selectModel(key: string): void {
    this.modelKey = key;
    this.router.navigate([], { relativeTo: this.route, queryParams: { model: key === 'active' ? null : key }, replaceUrl: true });
    this.loadInfo();
  }

  private loadInfo(): void {
    this.infoError = null;
    this.service.modelInfo(this.modelKey).subscribe({
      next: (info) => {
        this.info = info;
        const ids = info.units.map((u) => u.pcs_id);
        const wanted = Number(this.route.snapshot.queryParamMap.get('pcs'));
        this.selectUnit(ids.includes(this.pcsId ?? -1) ? this.pcsId! : ids.includes(wanted) ? wanted : ids.includes(6) ? 6 : ids[0]);
      },
      error: (err) => (this.infoError = err?.error?.detail || 'Could not load the model.')
    });
  }

  get unit(): Unit | undefined {
    return this.info?.units.find((u) => u.pcs_id === this.pcsId);
  }

  unitName(u: Unit): string {
    return `${u.site_name ?? u.system_name ?? ''} · ${u.pcs_code} · ${fmtNum(u.rated_power_kw, 0)} kW`;
  }

  selectUnit(id: number): void {
    this.pcsId = id;
    const u = this.unit;
    if (!u) {
      return;
    }
    this.point = this.blankPoint(id, this.point.direction, (u.rated_power_kw ?? 1000) * 0.5);
    this.pointSource = null;
    this.measuredEta = null;
    this.pointResult = null;
    this.cycle = this.blankCycle(id);
    this.cycleResult = null;
    this.predictPoint();
    this.predictCycle();
  }

  private blankPoint(id: number, direction: EffDirection = 'discharge', p = 500): EffPointIn {
    return {
      pcs_id: id,
      direction,
      p_kw: Math.round(p),
      power_factor: 1,
      dc_voltage_v: null,
      igbt_temp_c: null,
      heatsink_temp_c: null,
      inlet_coolant_temp_c: null,
      ambient_temp_c: null,
      ac_voltage_v: null,
      ac_frequency_hz: null,
      grid_service: 'NONE',
      age_years: null
    };
  }

  private blankCycle(id: number): EffCycleIn {
    const rated = this.info?.units.find((u) => u.pcs_id === id)?.rated_power_kw ?? 1000;
    return {
      pcs_id: id,
      charge_kw: Math.round(rated * 0.45),
      discharge_kw: Math.round(rated * 0.5),
      soc_min_pct: 10,
      soc_max_pct: 85,
      period_hours: 24,
      kwh_per_pct: null,
      cell_temp_avg_c: null,
      fr_share: 0.1,
      direction_changes: 1,
      soh_pct: null,
      aux_kw: null,
      dc_rte_pct: null,
      power_factor: 1,
      grid_service: 'NONE'
    };
  }

  // ---------------------------------------------------------------- operating point

  get loadPct(): number {
    const rated = this.unit?.rated_power_kw ?? 0;
    return rated ? (100 * (this.point.p_kw || 0)) / rated : 0;
  }

  setLoadPct(v: number): void {
    const rated = this.unit?.rated_power_kw ?? 0;
    this.point.p_kw = Math.round((rated * Number(v)) / 100);
    this.markEdited();
  }

  /** Placeholder: the unit's typical value at this load (used when the field is left empty). */
  typical(field: string): string {
    const t = this.pointResult?.inputs_used?.[field];
    return t === undefined ? 'typical' : `typical ${fmtNum(t, field.endsWith('_v') ? 0 : field === 'ac_frequency_hz' ? 3 : 1)}`;
  }

  markEdited(): void {
    if (this.pointSource) {
      this.pointSource = `${this.pointSource.replace(' (edited)', '')} (edited)`;
    }
  }

  setDirection(d: EffDirection): void {
    this.point.direction = d;
    this.markEdited();
    this.predictPoint();
  }

  typicalConditions(): void {
    const keep = this.point;
    this.point = { ...this.blankPoint(keep.pcs_id, keep.direction, keep.p_kw), power_factor: keep.power_factor, grid_service: keep.grid_service };
    this.pointSource = null;
    this.measuredEta = null;
    this.predictPoint();
  }

  loadLatest(direction: EffDirection): void {
    if (!this.pcsId) {
      return;
    }
    this.loadingSample = true;
    this.pointError = null;
    this.service.sample(this.modelKey, this.pcsId, direction).subscribe({
      next: (s) => {
        this.loadingSample = false;
        this.point = {
          pcs_id: s.pcs_id,
          direction: s.direction,
          p_kw: Math.round(s.p_kw * 10) / 10,
          power_factor: s.power_factor,
          dc_voltage_v: s.dc_voltage_v,
          igbt_temp_c: s.igbt_temp_c,
          heatsink_temp_c: s.heatsink_temp_c,
          inlet_coolant_temp_c: s.inlet_coolant_temp_c,
          ambient_temp_c: s.ambient_temp_c,
          ac_voltage_v: s.ac_voltage_v ? Math.round(s.ac_voltage_v * 10) / 10 : null,
          ac_frequency_hz: s.ac_frequency_hz,
          grid_service: (s.grid_service as GridService) ?? 'NONE',
          age_years: null
        };
        this.measuredEta = s.measured_eta_pct;
        this.pointSource = `latest ${direction} reading ${s.ts.replace('T', ' ').slice(0, 16)}`;
        this.predictPoint();
      },
      error: (err) => {
        this.loadingSample = false;
        this.pointError = err?.error?.detail || 'No reading found.';
      }
    });
  }

  predictPoint(): void {
    if (!this.pcsId || !(this.point.p_kw > 0)) {
      return;
    }
    this.predicting = true;
    this.pointError = null;
    const clean = (v: number | null) => (v === null || (v as unknown) === '' || Number.isNaN(Number(v)) ? null : Number(v));
    const body: EffPointIn = {
      ...this.point,
      p_kw: Number(this.point.p_kw),
      power_factor: Number(this.point.power_factor) || 1,
      dc_voltage_v: clean(this.point.dc_voltage_v),
      igbt_temp_c: clean(this.point.igbt_temp_c),
      heatsink_temp_c: clean(this.point.heatsink_temp_c),
      inlet_coolant_temp_c: clean(this.point.inlet_coolant_temp_c),
      ambient_temp_c: clean(this.point.ambient_temp_c),
      ac_voltage_v: clean(this.point.ac_voltage_v),
      ac_frequency_hz: clean(this.point.ac_frequency_hz),
      age_years: clean(this.point.age_years)
    };
    if (!this.auth.hasPermission('ml.run:execute')) {
      this.predicting = false;
      this.pointError = WHAT_IF_TRAINERS_ONLY;
      return;
    }
    this.service.predict(this.modelKey, body).subscribe({
      next: (r) => {
        this.predicting = false;
        this.pointResult = r;
        this.buildPointCharts();
      },
      error: (err) => {
        this.predicting = false;
        const d = err?.error?.detail;
        this.pointError = typeof d === 'string' ? d : 'Estimation failed.';
      }
    });
  }

  private buildPointCharts(): void {
    const r = this.pointResult;
    if (!r) {
      return;
    }
    const charge = r.direction === 'charge';
    const measured = (this.info?.points ?? [])
      .filter((p) => p.pcs_id === r.pcs_id && p.charge === charge)
      .map((p) => ({ x: p.load_frac, y: p.actual, test: p.set === 'test' }));
    this.pointCurve = curveChart(r.curves, r.direction, measured, {
      x: r.load_frac,
      y: r.models.hybrid.eta_pct,
      label: 'This operating point (hybrid)'
    });
    const top = r.shap.filter((s) => Math.abs(s.pp) >= 0.0005).slice(0, 10);
    this.shapHeight = Math.max(140, top.length * 26 + 40);
    this.shapChart = hbar(
      top.map((s) => s.label),
      top.map((s) => s.pp),
      top.map((s) => (s.pp >= 0 ? NEG : POS)),
      (v) => `${v >= 0 ? '+' : ''}${v.toFixed(3)} pp`,
      'Effect on η (percentage points)'
    );
    const b = r.breakdown_kw;
    this.breakdownChart = hbar(
      ['Constant (standby, gate drive)', 'Conduction (∝ I)', 'Ohmic (∝ I²)', 'Boosting correction'],
      [b.constant, b.conduction, b.ohmic, b.residual],
      BREAKDOWN_COLORS,
      (v) => `${v.toFixed(2)} kW`,
      'Loss (kW)'
    );
  }

  bestKey(): EffModelKey {
    return 'hybrid';
  }

  diff(k: EffModelKey): string {
    if (this.measuredEta === null || !this.pointResult) {
      return '';
    }
    const d = this.pointResult.models[k].eta_pct - this.measuredEta;
    return `${d >= 0 ? '+' : ''}${d.toFixed(3)} pp vs measured`;
  }

  // ---------------------------------------------------------------- cycle

  get cyclePlaceholders() {
    const c = this.unit?.cycle;
    const dm = this.info?.dc_rte_model;
    return {
      kwh: c?.kwh_per_pct ? `unit ${fmtNum(c.kwh_per_pct, 1)}` : 'from rated energy',
      aux: c?.aux_kw_avg ? `unit avg ${fmtNum(c.aux_kw_avg, 1)}` : '0',
      temp: dm?.medians['cell_temp_avg_c'] !== undefined ? `typical ${fmtNum(dm.medians['cell_temp_avg_c'], 1)}` : 'typical',
      soh: dm?.medians['soh_pct'] !== undefined ? `typical ${fmtNum(dm.medians['soh_pct'], 2)}` : 'typical',
      dc: dm ? 'from the regression' : c?.rte_dc_median ? `unit median ${fmtNum(c.rte_dc_median, 2)}` : 'required'
    };
  }

  predictCycle(): void {
    if (!this.pcsId) {
      return;
    }
    this.cycling = true;
    this.cycleError = null;
    const opt = (v: number | null) => (v === null || (v as unknown) === '' || Number.isNaN(Number(v)) ? null : Number(v));
    const c = this.cycle;
    const body: EffCycleIn = {
      ...c,
      charge_kw: Number(c.charge_kw),
      discharge_kw: Number(c.discharge_kw),
      soc_min_pct: Number(c.soc_min_pct),
      soc_max_pct: Number(c.soc_max_pct),
      period_hours: Number(c.period_hours),
      fr_share: Number(c.fr_share),
      direction_changes: Number(c.direction_changes),
      power_factor: Number(c.power_factor) || 1,
      kwh_per_pct: opt(c.kwh_per_pct),
      cell_temp_avg_c: opt(c.cell_temp_avg_c),
      soh_pct: opt(c.soh_pct),
      aux_kw: opt(c.aux_kw),
      dc_rte_pct: opt(c.dc_rte_pct)
    };
    if (!this.auth.hasPermission('ml.run:execute')) {
      this.cycling = false;
      this.cycleError = WHAT_IF_TRAINERS_ONLY;
      return;
    }
    this.service.cycle(this.modelKey, body).subscribe({
      next: (r) => {
        this.cycling = false;
        this.cycleResult = r;
        const l = r.losses_kwh;
        this.lossChart = hbar(
          ['PCS · charging', 'Battery (DC round trip)', 'PCS · discharging', 'Auxiliaries + HVAC'],
          [l.pcs_charge, l.battery, l.pcs_discharge, l.auxiliaries],
          [LOSS_COLORS.pcs, LOSS_COLORS.battery, LOSS_COLORS.pcs, LOSS_COLORS.aux],
          (v) => `${v.toFixed(1)} kWh`,
          'Energy lost over the cycle (kWh)'
        );
      },
      error: (err) => {
        this.cycling = false;
        const d = err?.error?.detail;
        this.cycleError = typeof d === 'string' ? d : 'Calculation failed.';
      }
    });
  }

  hours(h: number): string {
    const m = Math.round(h * 60);
    return `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, '0')}`;
  }
}
