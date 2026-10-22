import { CommonModule } from '@angular/common';
import { Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';

import {
  SocEstMethod,
  SocEstModelOption,
  SocEstPoint,
  SocEstSystem,
  SocEstimate,
  SocStepResult
} from '../../../core/models/soc-estimation.model';
import { SocEstimationService } from '../../../core/services/soc-estimation.service';
import { ChartCanvasComponent } from '../../telemetry/graphs/chart-canvas.component';
import { AnyConfig, ms } from '../price-forecast-shared/pf-charts';
import { BANDED, EST_COLORS, EST_DASH, EST_LABELS, EST_ORDER, SCOPE_LABELS, measureChart, timelineChart } from '../soc-estimation-shared/soc-est-charts';

type Tab = 'estimate' | 'timeline' | 'step';

interface StepForm {
  ts: string;
  dt_min: number;
  soc: number;
  sigma_soc: number;
  bias: number;
  gain: number;
  direction: 'CHARGE' | 'DISCHARGE' | 'MEAN';
  last_recal_ts: string;
  soc_coulomb_pct: number | null;
  measured_current_a: number | null;
  current_sensor_offset_a: number | null;
  pack_voltage_v: number | null;
  cell_v_avg_v: number | null;
  ocv_rested_v: number | null;
  cell_temp_avg_c: number | null;
  usable_capacity_ah: number | null;
  c_rate: number | null;
  coulombic_efficiency: number | null;
  at_rest: boolean;
  rest_duration_min: number | null;
  anchor_soc_pct: number | null;
  anchor_method: '' | 'FULL_CHARGE' | 'REST_OCV';
}

const FEATURE_FIELDS: { key: keyof StepForm; label: string; step: number; required?: boolean }[] = [
  { key: 'soc_coulomb_pct', label: 'Coulomb SOC (%)', step: 0.1, required: true },
  { key: 'measured_current_a', label: 'Measured current (A, + charge)', step: 1, required: true },
  { key: 'current_sensor_offset_a', label: 'Sensor offset (A)', step: 0.1 },
  { key: 'usable_capacity_ah', label: 'Usable capacity (Ah)', step: 1, required: true },
  { key: 'coulombic_efficiency', label: 'Coulombic efficiency', step: 0.001 },
  { key: 'cell_temp_avg_c', label: 'Cell temp avg (°C)', step: 0.1 },
  { key: 'pack_voltage_v', label: 'Pack voltage (V)', step: 0.1 },
  { key: 'cell_v_avg_v', label: 'Cell V avg (V)', step: 0.001 },
  { key: 'c_rate', label: 'C-rate', step: 0.01 },
  { key: 'rest_duration_min', label: 'Rest duration (min)', step: 5 },
  { key: 'ocv_rested_v', label: 'Rested OCV (V / cell)', step: 0.0001 }
];

/** Insights -> Battery health -> SOC Estimator: the corrected SOC per system (live with the carried EKF state, or
 *  replayed as of a time), the run's timeline against anchors and truth, and a single EKF step for the I/O contract. */
@Component({
  selector: 'app-soc-estimator',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink, ChartCanvasComponent],
  templateUrl: './soc-estimator.component.html',
  styleUrls: ['../soh-estimator/soh-estimator.component.scss', '../price-forecast/price-forecast.component.scss', './soc-estimator.component.scss']
})
export class SocEstimatorComponent implements OnInit {
  readonly colors = EST_COLORS;
  readonly labels = EST_LABELS;
  readonly dash = EST_DASH;
  readonly order = EST_ORDER;
  readonly banded = BANDED;
  readonly scopeLabels = SCOPE_LABELS;
  readonly featureFields = FEATURE_FIELDS;
  readonly historyOptions = [6, 12, 24, 48, 72];

  models: SocEstModelOption[] = [];
  modelsLoaded = false;
  modelsError: string | null = null;
  modelKey = 'active';
  systems: SocEstSystem[] = [];
  systemId: number | null = null;
  tab: Tab = 'estimate';

  // estimate
  mode: 'live' | 'asof' = 'live';
  asOf = '';
  historyH = 24;
  loading = false;
  error: string | null = null;
  est: SocEstimate | null = null;
  estMethods = new Set<SocEstMethod>(['coulomb', 'bms', 'ekf', 'hybrid']);
  estBand: SocEstMethod = 'hybrid';
  estChart?: AnyConfig;
  driftChart?: AnyConfig;

  // timeline
  range: { from: string | null; to: string | null; test_from: string | null } | null = null;
  tlFrom = '';
  tlTo = '';
  tlLoading = false;
  tlError: string | null = null;
  tlPoints: SocEstPoint[] = [];
  tlMethods = new Set<SocEstMethod>(['coulomb', 'ocv_lookup', 'ekf', 'hybrid']);
  tlBand: SocEstMethod = 'hybrid';
  tlTruth = true;
  tlChart?: AnyConfig;
  errChart?: AnyConfig;
  biasChart?: AnyConfig;

  // single step
  form: StepForm = this.blankForm();
  stepping = false;
  stepError: string | null = null;
  stepResult: SocStepResult | null = null;

  constructor(private service: SocEstimationService, private route: ActivatedRoute, private router: Router) {}

  ngOnInit(): void {
    this.modelKey = this.route.snapshot.queryParamMap.get('model') ?? 'active';
    this.service.options().subscribe({ next: (o) => (this.systems = o.systems), error: () => undefined });
    this.service.models().subscribe({
      next: (m) => {
        this.models = m;
        this.modelsLoaded = true;
        if (m.length) {
          this.pickSystem();
        }
      },
      error: (err) => {
        this.modelsLoaded = true;
        this.modelsError = err?.status === 0 ? 'Could not reach the ML service. Is it running on port 8100?' : 'Could not load the models.';
      }
    });
  }

  get model(): SocEstModelOption | null {
    return this.modelKey === 'active' ? this.models[0] ?? null : this.models.find((m) => String(m.run_id) === this.modelKey) ?? null;
  }

  optionLabel(m: SocEstModelOption): string {
    const best = m.best_method && m.primary_scope ? m.metrics?.[m.best_method]?.[m.primary_scope]?.rmse : null;
    return `#${m.run_id}${m.run_name ? ' · ' + m.run_name : ''}${m.is_default ? ' (default)' : ''} · ${m.label_source} labels` +
      (best !== null && best !== undefined ? ` · RMSE ${best.toFixed(2)}` : '');
  }

  systemName(id: number | null): string {
    const s = this.systems.find((x) => x.system_id === id);
    return s ? `${s.system_name}${s.site_name ? ' · ' + s.site_name : ''}` : `System ${id}`;
  }

  selectModel(key: string): void {
    this.modelKey = key;
    this.router.navigate([], { relativeTo: this.route, queryParams: { model: key === 'active' ? null : key }, replaceUrl: true });
    this.pickSystem();
  }

  private pickSystem(): void {
    const ids = this.model?.system_ids ?? [];
    if (!ids.includes(this.systemId as number)) {
      this.systemId = ids[0] ?? null;
    }
    this.onContext();
  }

  selectSystem(id: number): void {
    this.systemId = id;
    this.onContext();
  }

  setTab(t: Tab): void {
    this.tab = t;
    this.onContext();
  }

  private onContext(): void {
    this.est = null;
    this.tlPoints = [];
    this.range = null;
    this.stepResult = null;
    if (!this.model || this.systemId === null) {
      return;
    }
    if (this.tab === 'estimate') {
      this.runEstimate();
    } else if (this.tab === 'timeline') {
      this.loadRange();
    }
  }

  // ---------------------------------------------------------------- estimate

  runEstimate(reset = false): void {
    if (!this.model || this.systemId === null) {
      return;
    }
    if (this.mode === 'asof' && !this.asOf) {
      this.error = 'Enter the as-of time';
      return;
    }
    this.loading = true;
    this.error = null;
    this.service
      .estimate(String(this.model.run_id), this.systemId, this.mode === 'asof' ? this.asOf : null, this.historyH, reset)
      .subscribe({
        next: (e) => {
          this.est = e;
          this.loading = false;
          this.buildEstimate();
        },
        error: (err) => {
          this.loading = false;
          this.est = null;
          this.error = this.detail(err, 'Estimation failed.');
        }
      });
  }

  toggleEst(m: SocEstMethod): void {
    this.estMethods.has(m) ? this.estMethods.delete(m) : this.estMethods.add(m);
    this.estMethods = new Set(this.estMethods);
    this.buildEstimate();
  }

  buildEstimate(): void {
    const e = this.est;
    if (!e?.trajectory.length) {
      this.estChart = this.driftChart = undefined;
      return;
    }
    const methods = EST_ORDER.filter((m) => this.estMethods.has(m));
    this.estChart = timelineChart({ points: e.trajectory, methods, band: this.estBand, showTruth: false });
    this.driftChart = measureChart(
      [
        {
          label: 'Drift correction (hybrid − coulomb)',
          color: EST_COLORS.hybrid,
          points: e.trajectory.map((p) => ({ x: ms(p.ts), y: p.hybrid !== null && p.coulomb !== null ? p.hybrid - p.coulomb : null }))
        }
      ],
      'SOC pts',
      'Correction (SOC points)'
    );
  }

  inputKeys(): string[] {
    return Object.keys(this.est?.inputs ?? {});
  }

  contract(e: SocEstimate | SocStepResult): string {
    return JSON.stringify(
      {
        system_id: e.system_id,
        ts: e.ts,
        soc_corrected_pct: this.round(e.soc_corrected_pct),
        p10: this.round(e.p10),
        p90: this.round(e.p90),
        drift_correction_pct: this.round(e.drift_correction_pct),
        recalibrated: e.recalibrated,
        ...('flags' in e ? { stale: e.flags.stale, no_anchor: e.flags.no_anchor } : {})
      },
      null,
      2
    );
  }

  // ---------------------------------------------------------------- timeline

  loadRange(): void {
    if (!this.model || this.systemId === null) {
      return;
    }
    this.service.range(this.model.run_id, this.systemId).subscribe({
      next: (r) => {
        this.range = r;
        const start = (r.test_from ?? r.from ?? '').slice(0, 10);
        this.tlFrom = start ? `${start}T00:00` : '';
        this.tlTo = start ? `${this.addDays(start, 2)}T00:00` : '';
        this.loadTimeline();
      },
      error: (err) => (this.tlError = this.detail(err, 'Could not load the run.'))
    });
  }

  shiftDays(n: number): void {
    if (!this.tlFrom || !this.tlTo) {
      return;
    }
    this.tlFrom = `${this.addDays(this.tlFrom.slice(0, 10), n)}${this.tlFrom.slice(10)}`;
    this.tlTo = `${this.addDays(this.tlTo.slice(0, 10), n)}${this.tlTo.slice(10)}`;
    this.loadTimeline();
  }

  loadTimeline(): void {
    if (!this.model || this.systemId === null || !this.tlFrom || !this.tlTo) {
      return;
    }
    this.tlLoading = true;
    this.tlError = null;
    this.service.points(this.model.run_id, this.systemId, this.plantIso(this.tlFrom), this.plantIso(this.tlTo)).subscribe({
      next: (p) => {
        this.tlPoints = p;
        this.tlLoading = false;
        this.buildTimeline();
      },
      error: (err) => {
        this.tlLoading = false;
        this.tlError = this.detail(err, 'Could not load the timeline.');
      }
    });
  }

  toggleTl(m: SocEstMethod): void {
    this.tlMethods.has(m) ? this.tlMethods.delete(m) : this.tlMethods.add(m);
    this.tlMethods = new Set(this.tlMethods);
    this.buildTimeline();
  }

  get hasTruth(): boolean {
    return this.tlPoints.some((p) => p.truth !== null && p.truth !== undefined);
  }

  get testFromMs(): number | null {
    const t = this.range?.test_from;
    if (!t || !this.tlPoints.length) {
      return null;
    }
    const x = ms(t);
    return x > ms(this.tlPoints[0].ts) && x < ms(this.tlPoints[this.tlPoints.length - 1].ts) ? x : null;
  }

  get windowStats(): { m: SocEstMethod; rmse: number | null; max: number | null }[] {
    const pts = this.tlPoints.filter((p) => p.truth !== null && p.truth !== undefined);
    return EST_ORDER.map((m) => {
      const e = pts.map((p) => Number(p[m as keyof SocEstPoint] ?? NaN) - (p.truth as number)).filter((v) => Number.isFinite(v));
      return {
        m,
        rmse: e.length ? Math.sqrt(e.reduce((a, v) => a + v * v, 0) / e.length) : null,
        max: e.length ? Math.max(...e.map(Math.abs)) : null
      };
    });
  }

  buildTimeline(): void {
    const pts = this.tlPoints;
    if (!pts.length) {
      this.tlChart = this.errChart = this.biasChart = undefined;
      return;
    }
    const methods = EST_ORDER.filter((m) => this.tlMethods.has(m));
    this.tlChart = timelineChart({
      points: pts,
      methods,
      band: this.tlBand,
      showTruth: this.tlTruth,
      markerFrom: this.testFromMs,
      markerLabel: 'test period →'
    });
    this.errChart = this.hasTruth
      ? measureChart(
          methods.map((m) => ({
            label: EST_LABELS[m],
            color: EST_COLORS[m],
            dash: EST_DASH[m],
            points: pts.map((p) => {
              const v = p[m as keyof SocEstPoint] as number | null;
              return { x: ms(p.ts), y: v !== null && v !== undefined && p.truth !== null && p.truth !== undefined ? v - p.truth : null };
            })
          })),
          'SOC pts',
          'Estimate − true SOC (SOC points)'
        )
      : undefined;
    this.biasChart = measureChart(
      [{ label: 'EKF residual sensor bias', color: EST_COLORS.ekf, points: pts.map((p) => ({ x: ms(p.ts), y: p.ekf_bias })) }],
      'A',
      'Bias (A)',
      false
    );
  }

  // ---------------------------------------------------------------- single step

  blankForm(): StepForm {
    return {
      ts: '',
      dt_min: 5,
      soc: 50,
      sigma_soc: 1,
      bias: 0,
      gain: 1,
      direction: 'MEAN',
      last_recal_ts: '',
      soc_coulomb_pct: 50,
      measured_current_a: 0,
      current_sensor_offset_a: 0,
      pack_voltage_v: null,
      cell_v_avg_v: null,
      ocv_rested_v: null,
      cell_temp_avg_c: 25,
      usable_capacity_ah: 1670,
      c_rate: null,
      coulombic_efficiency: 1,
      at_rest: false,
      rest_duration_min: 0,
      anchor_soc_pct: null,
      anchor_method: ''
    };
  }

  /** Prefill the step form from the newest estimate: its state and the inputs of its last row. */
  fillFromEstimate(): void {
    const e = this.est;
    if (!e) {
      return;
    }
    const i = e.inputs;
    const n = (k: string) => (typeof i[k] === 'number' ? (i[k] as number) : null);
    const sig = e.ekf.p90 !== null && e.ekf.p10 !== null ? (e.ekf.p90 - e.ekf.p10) / 2.563 : 1;
    this.form = {
      ...this.form,
      ts: this.local(e.ts, 5),
      soc: this.round(e.ekf.soc) ?? 50,
      sigma_soc: Math.max(0.01, this.round(sig) ?? 1),
      bias: this.round(e.ekf.bias_a) ?? 0,
      gain: Number((e.ekf.gain ?? 1).toFixed(4)),
      direction: (e.ekf.direction as StepForm['direction']) ?? 'MEAN',
      last_recal_ts: e.last_recal_ts ? this.local(e.last_recal_ts) : '',
      soc_coulomb_pct: n('soc_coulomb_pct'),
      measured_current_a: n('measured_current_a'),
      current_sensor_offset_a: n('current_sensor_offset_a'),
      pack_voltage_v: n('pack_voltage_v'),
      cell_v_avg_v: n('cell_v_avg_v'),
      ocv_rested_v: n('ocv_rested_v'),
      cell_temp_avg_c: n('cell_temp_avg_c'),
      usable_capacity_ah: n('usable_capacity_ah'),
      c_rate: n('c_rate'),
      coulombic_efficiency: n('coulombic_efficiency'),
      at_rest: !!i['at_rest'],
      rest_duration_min: n('rest_duration_min')
    };
    this.tab = 'step';
  }

  get stepProblem(): string | null {
    const f = this.form;
    if (f.soc_coulomb_pct === null || f.measured_current_a === null || !f.usable_capacity_ah) {
      return 'Coulomb SOC, measured current and usable capacity are required';
    }
    if (f.ocv_rested_v !== null && (f.ocv_rested_v < 1.5 || f.ocv_rested_v > 4.5)) {
      return 'Rested OCV is per cell (1.5–4.5 V)';
    }
    if (f.anchor_method && f.anchor_soc_pct === null) {
      return 'Enter the anchor SOC for the anchor method';
    }
    return null;
  }

  runStep(): void {
    if (!this.model || this.systemId === null || this.stepProblem) {
      return;
    }
    const f = this.form;
    const num = (v: number | null) => (v === null || (v as any) === '' ? null : Number(v));
    this.stepping = true;
    this.stepError = null;
    this.service
      .step(String(this.model.run_id), {
        system_id: this.systemId,
        ts: f.ts || null,
        dt_min: Number(f.dt_min),
        state: {
          soc: Number(f.soc),
          bias: Number(f.bias),
          gain: Number(f.gain),
          sigma_soc: Number(f.sigma_soc),
          direction: f.direction,
          last_recal_ts: f.last_recal_ts || null
        },
        features: {
          soc_coulomb_pct: num(f.soc_coulomb_pct),
          measured_current_a: num(f.measured_current_a),
          current_sensor_offset_a: num(f.current_sensor_offset_a) ?? 0,
          pack_voltage_v: num(f.pack_voltage_v),
          cell_v_avg_v: num(f.cell_v_avg_v),
          ocv_rested_v: f.at_rest ? num(f.ocv_rested_v) : null,
          cell_temp_avg_c: num(f.cell_temp_avg_c) ?? 25,
          usable_capacity_ah: num(f.usable_capacity_ah),
          c_rate: num(f.c_rate),
          coulombic_efficiency: num(f.coulombic_efficiency) ?? 1,
          at_rest: f.at_rest,
          rest_duration_min: num(f.rest_duration_min) ?? 0
        },
        anchor_soc_pct: f.anchor_method ? num(f.anchor_soc_pct) : null,
        anchor_method: f.anchor_method || null
      })
      .subscribe({
        next: (r) => {
          this.stepResult = r;
          this.stepping = false;
        },
        error: (err) => {
          this.stepping = false;
          this.stepError = this.detail(err, 'The step failed.');
        }
      });
  }

  /** Carry the step's output state into the form, for the next step. */
  carryState(): void {
    const r = this.stepResult;
    if (!r) {
      return;
    }
    this.form = {
      ...this.form,
      ts: this.local(r.ts, this.form.dt_min),
      soc: this.round(r.ekf.soc) ?? this.form.soc,
      sigma_soc: Math.max(0.01, this.round(r.sigma_soc) ?? this.form.sigma_soc),
      bias: this.round(r.ekf.bias_a) ?? this.form.bias,
      gain: Number((r.ekf.gain ?? this.form.gain).toFixed(4)),
      direction: (r.ekf.direction as StepForm['direction']) ?? this.form.direction,
      last_recal_ts: r.last_recal_ts ? this.local(r.last_recal_ts) : this.form.last_recal_ts,
      soc_coulomb_pct: this.form.soc_coulomb_pct,
      rest_duration_min: this.form.at_rest ? Number(this.form.rest_duration_min ?? 0) + Number(this.form.dt_min) : 0,
      anchor_soc_pct: null,
      anchor_method: ''
    };
    this.stepResult = null;
  }

  // ---------------------------------------------------------------- helpers

  num(v: number | null | undefined, d = 2): string {
    return typeof v === 'number' && Number.isFinite(v) ? v.toFixed(d) : '—';
  }

  signed(v: number | null | undefined, d = 2): string {
    return typeof v === 'number' && Number.isFinite(v) ? `${v > 0 ? '+' : ''}${v.toFixed(d)}` : '—';
  }

  round(v: number | null | undefined, d = 2): number | null {
    return typeof v === 'number' && Number.isFinite(v) ? Number(v.toFixed(d)) : null;
  }

  timeOf(ts: string | null | undefined): string {
    return ts ? ts.replace('T', ' ').slice(0, 16) : '—';
  }

  hours(v: number | null | undefined): string {
    if (typeof v !== 'number' || !Number.isFinite(v)) {
      return '—';
    }
    return v < 1 ? `${Math.round(v * 60)} min` : v < 48 ? `${v.toFixed(1)} h` : `${(v / 24).toFixed(1)} days`;
  }

  /** Plant wall-clock time 'YYYY-MM-DDTHH:mm' of an ISO time (optionally plus minutes). */
  private local(iso: string, plusMin = 0): string {
    const t = new Date(new Date(iso).getTime() + plusMin * 60000 + 330 * 60000);
    return t.toISOString().slice(0, 16);
  }

  private plantIso(local: string): string {
    return `${local.length === 16 ? local + ':00' : local}+05:30`;
  }

  private addDays(d: string, n: number): string {
    const t = new Date(`${d}T00:00:00Z`);
    t.setUTCDate(t.getUTCDate() + n);
    return t.toISOString().slice(0, 10);
  }

  private detail(err: any, fallback: string): string {
    if (err?.status === 0) {
      return 'Could not reach the ML service. Is it running on port 8100?';
    }
    const d = err?.error?.detail;
    if (Array.isArray(d)) {
      return d.map((x: any) => `${(x.loc ?? []).slice(1).join('.')}: ${x.msg}`).join('; ');
    }
    return typeof d === 'string' ? d : d?.message || fallback;
  }
}
