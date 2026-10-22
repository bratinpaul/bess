import { CommonModule } from '@angular/common';
import { Component, OnDestroy, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { TooltipItem } from 'chart.js';

import {
  NfModelKey,
  NfModelSpec,
  NfOptions,
  NfPeak,
  NfPreviewUnit,
  NfRegressorKey,
  NfRun,
  NfRunDetail,
  NfScores,
  NfUnit
} from '../../../core/models/netload-forecast.model';
import { NetloadForecastService } from '../../../core/services/netload-forecast.service';
import { ChartCanvasComponent } from '../../telemetry/graphs/chart-canvas.component';
import { AnyConfig, NF_COLORS, NF_DASH, NF_LABELS, NF_ORDER, THRESHOLD, axis, legend, tooltip } from '../netload-forecast-shared/nf-charts';

interface ScoreCol {
  key: keyof NfScores;
  label: string;
  better: 'low' | 'high' | 'target80' | 'zero';
  digits: number;
  help: string;
  scale?: number;
}

const LOAD_COLS: ScoreCol[] = [
  { key: 'mae', label: 'MAE', better: 'low', digits: 1, help: 'Mean absolute error of P50 (kW), every 5-min target' },
  { key: 'rmse', label: 'RMSE', better: 'low', digits: 1, help: 'Root mean squared error of P50 (kW)' },
  { key: 'mape_pct', label: 'MAPE %', better: 'low', digits: 2, help: 'Mean absolute percentage error' },
  { key: 'bias', label: 'Bias', better: 'zero', digits: 1, help: 'Mean P50 − actual (kW): + = forecast too high' },
  { key: 'pinball', label: 'Pinball', better: 'low', digits: 2, help: 'Quantile loss over P10 / P50 / P90 - scores the whole band' },
  { key: 'coverage_pct', label: 'P10–P90 cover %', better: 'target80', digits: 1, help: 'Share of readings inside P10–P90 (80 % is right)' },
  { key: 'width_kw', label: 'Width', better: 'low', digits: 0, help: 'Mean P90 − P10 (kW): narrower is better at the right coverage' },
  { key: 'skill_mae_pct', label: 'Skill vs naïve %', better: 'high', digits: 1, help: '1 − MAE / MAE of the seasonal naïve' },
  { key: 'window_mae', label: 'Billing-window MAE', better: 'low', digits: 1, help: 'MAE inside the billing-peak window - where demand charges are set' }
];

const PEAK_COLS: ScoreCol[] = [
  { key: 'peak_mae_kw', label: 'Peak MAE', better: 'low', digits: 1, help: 'Daily billing-window peak: |forecast P50 peak − actual peak| (kW)' },
  { key: 'peak_bias_kw', label: 'Peak bias', better: 'zero', digits: 1, help: 'Mean forecast − actual peak (kW)' },
  { key: 'peak_time_mae_min', label: 'Timing error (min)', better: 'low', digits: 0, help: 'Mean |forecast peak time − actual peak time|' },
  { key: 'exceed_brier', label: 'Brier', better: 'low', digits: 3, help: 'Mean squared error of P(peak > threshold): lower is better' },
  { key: 'exceed_auc', label: 'AUC', better: 'high', digits: 3, help: 'Ranks breach days above the others (0.5 = no skill); needs breach and non-breach days' },
  { key: 'exceed_recall', label: 'Recall', better: 'high', digits: 0, scale: 100, help: 'Breach days called (p ≥ 50 %), %' },
  { key: 'exceed_precision', label: 'Precision', better: 'high', digits: 0, scale: 100, help: 'Called days that breached, %' }
];

/** ML Model -> Net-load Forecast: configure, train and compare the net-load & peak forecasters. */
@Component({
  selector: 'app-netload-forecast-model',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink, ChartCanvasComponent],
  templateUrl: './netload-forecast-model.component.html',
  styleUrls: [
    '../model-training/model-training.component.scss',
    '../price-forecast-model/price-forecast-model.component.scss',
    './netload-forecast-model.component.scss'
  ]
})
export class NetloadForecastModelComponent implements OnInit, OnDestroy {
  readonly loadCols = LOAD_COLS;
  readonly peakCols = PEAK_COLS;
  readonly colors = NF_COLORS;
  readonly labels = NF_LABELS;

  options: NfOptions | null = null;
  optionsError: string | null = null;

  mpIds = new Set<number>();
  dateFrom = '';
  dateTo = '';
  groups = new Set<string>();
  weatherSource: 'forecast' | 'actual' = 'forecast';
  threshold: number | null = null;
  chosen = new Set<NfModelKey>();
  params: Record<string, Record<string, number>> = {};
  openParams: NfModelKey | null = null;
  horizon = 48;
  testPct = 25;
  originStep = 3;
  trainStep = 2;
  runName = '';
  makeDefault = true;

  preview: NfPreviewUnit[] = [];
  previewing = false;
  previewChart?: AnyConfig;
  training = false;
  trainError: string | null = null;
  elapsed = 0;
  private timer?: ReturnType<typeof setInterval>;
  private previewTimer?: ReturnType<typeof setTimeout>;

  runs: NfRun[] = [];
  runsLoading = true;
  run: NfRunDetail | null = null;
  runLoading = false;

  leadChart?: AnyConfig;
  hourChart?: AnyConfig;
  peakChart?: AnyConfig;
  importanceChart?: AnyConfig;
  importanceHeight = 300;
  importanceModel = 'lightgbm';
  peakRows: NfPeak[] = [];

  constructor(private service: NetloadForecastService, private route: ActivatedRoute, private router: Router) {}

  ngOnInit(): void {
    this.service.options().subscribe({
      next: (o) => {
        this.options = o;
        this.groups = new Set(o.feature_groups.map((g) => g.key));
        this.mpIds = new Set(o.units.filter((u) => u.readings > 0).map((u) => u.mp_id));
        this.chosen = new Set(o.models.map((m) => m.key));
        this.horizon = o.defaults.horizon_hours;
        this.testPct = o.defaults.test_fraction * 100;
        this.originStep = o.defaults.origin_step_h;
        this.trainStep = o.defaults.train_origin_step_h;
        this.resetParams();
        this.schedulePreview();
      },
      error: (err) =>
        (this.optionsError = err?.status === 0 ? 'Could not reach the ML service. Is it running on port 8100?' : 'Could not load the options.')
    });
    this.loadRuns(Number(this.route.snapshot.queryParamMap.get('run')) || null);
  }

  ngOnDestroy(): void {
    clearTimeout(this.previewTimer);
    clearInterval(this.timer);
  }

  // ---------------------------------------------------------------- inputs

  resetParams(): void {
    this.params = Object.fromEntries((this.options?.models ?? []).map((m) => [m.key, Object.fromEntries(m.params.map((p) => [p.name, p.default]))]));
  }

  unitLabel(u: NfUnit): string {
    return `${u.mp_code} · ${u.site_name ?? 'site ' + u.site_id}${u.voltage_kv ? ' · ' + u.voltage_kv + ' kV' : ''}`;
  }

  shortUnit(id: number | string): string {
    return this.options?.units.find((x) => x.mp_id === Number(id))?.mp_code ?? `MP ${id}`;
  }

  tariffOf(id: number | string) {
    return this.options?.tariffs[String(id)] ?? null;
  }

  get firstTariff() {
    const id = Array.from(this.mpIds)[0];
    return id ? this.tariffOf(id) : null;
  }

  toggleUnit(u: NfUnit): void {
    if (!u.readings) {
      return;
    }
    this.mpIds.has(u.mp_id) ? this.mpIds.delete(u.mp_id) : this.mpIds.add(u.mp_id);
    this.mpIds = new Set(this.mpIds);
    this.schedulePreview();
  }

  toggleGroup(key: string, required: boolean): void {
    if (required) {
      return;
    }
    this.groups.has(key) ? this.groups.delete(key) : this.groups.add(key);
    this.groups = new Set(this.groups);
  }

  toggleModel(m: NfModelSpec): void {
    if (m.always) {
      return;
    }
    this.chosen.has(m.key) ? this.chosen.delete(m.key) : this.chosen.add(m.key);
    this.chosen = new Set(this.chosen);
  }

  familyLabel(f: string): string {
    return { baseline: 'Baseline', primary: 'Primary', deep: 'Deep multi-horizon', peak: 'Peak exceedance (daily)' }[f] ?? f;
  }

  schedulePreview(): void {
    clearTimeout(this.previewTimer);
    this.previewTimer = setTimeout(() => this.loadPreview(), 450);
  }

  private selection() {
    return {
      mp_ids: Array.from(this.mpIds),
      date_from: this.dateFrom || null,
      date_to: this.dateTo || null,
      feature_groups: Array.from(this.groups),
      weather_source: this.weatherSource,
      peak_threshold_kw: this.threshold ? Number(this.threshold) : null
    };
  }

  private loadPreview(): void {
    if (!this.mpIds.size) {
      this.preview = [];
      this.previewChart = undefined;
      return;
    }
    this.previewing = true;
    this.service.preview(this.selection()).subscribe({
      next: (p) => {
        this.preview = p.units;
        this.previewing = false;
        this.buildPreviewChart();
      },
      error: () => {
        this.preview = [];
        this.previewing = false;
      }
    });
  }

  get autoThreshold(): number | null {
    const v = this.preview.find((u) => u.peak_p75)?.peak_p75;
    return v ? Math.round(v / 10) * 10 : null;
  }

  /** Daily billing-window peaks of the selection, workdays and other days told apart, with the threshold. */
  buildPreviewChart(): void {
    const u = this.preview.find((x) => x.peaks?.length);
    if (!u?.peaks) {
      this.previewChart = undefined;
      return;
    }
    const peaks = u.peaks;
    const thr = this.threshold ? Number(this.threshold) : this.autoThreshold;
    const labels = peaks.map((p) => p.date.slice(5));
    this.previewChart = {
      type: 'bar',
      data: {
        labels,
        datasets: [
          {
            label: 'Workday peak',
            data: peaks.map((p) => (p.workday ? p.peak : null)),
            backgroundColor: '#2a78d6',
            borderRadius: 3,
            barPercentage: 0.85,
            categoryPercentage: 1,
            grouped: false
          } as any,
          {
            label: 'Weekend / holiday peak',
            data: peaks.map((p) => (p.workday ? null : p.peak)),
            backgroundColor: '#9aa1ab',
            borderRadius: 3,
            barPercentage: 0.85,
            categoryPercentage: 1,
            grouped: false
          } as any,
          ...(thr
            ? [{ type: 'line', label: `Threshold ${thr} kW`, data: peaks.map(() => thr), borderColor: THRESHOLD, borderDash: [6, 4], borderWidth: 1.4, pointRadius: 0 } as any]
            : [])
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        plugins: {
          legend: legend(),
          tooltip: { ...tooltip, callbacks: { label: (ctx: TooltipItem<'bar'>) => `${ctx.dataset.label}: ${Number(ctx.parsed.y).toFixed(0)} kW` } }
        },
        scales: {
          x: axis(undefined, { grid: { display: false }, ticks: { color: '#6b6f76', maxRotation: 0, autoSkip: true, font: { size: 10 } } }),
          y: axis('kW', { suggestedMin: Math.max(0, Math.min(...peaks.map((p) => p.peak ?? 0)) * 0.7) })
        }
      }
    } as AnyConfig;
  }

  get problem(): string | null {
    if (!this.mpIds.size) {
      return 'Choose a metering point';
    }
    if (!this.chosen.size) {
      return 'Choose at least one model';
    }
    const days = Math.max(0, ...this.preview.map((u) => u.days ?? 0));
    const need = 7 + Math.ceil(Number(this.horizon) / 24) + 2;
    if (this.preview.length && days < need) {
      return `Needs about ${need} days of demand (7 days of history + horizon + a test period); the selection has ${days}`;
    }
    return null;
  }

  train(): void {
    if (this.problem || this.training) {
      return;
    }
    this.training = true;
    this.trainError = null;
    this.elapsed = 0;
    this.timer = setInterval(() => this.elapsed++, 1000);
    const models = Array.from(this.chosen);
    this.service
      .train({
        ...this.selection(),
        models,
        params: Object.fromEntries(models.map((k) => [k, this.params[k] ?? {}])),
        horizon_hours: Number(this.horizon),
        test_fraction: Number(this.testPct) / 100,
        origin_step_h: Number(this.originStep),
        train_origin_step_h: Number(this.trainStep),
        random_state: 42,
        run_name: this.runName.trim() || null,
        make_default: this.makeDefault
      })
      .subscribe({
        next: (run) => {
          this.stopTimer();
          this.loadRuns(run.run_id);
        },
        error: (err) => {
          this.stopTimer();
          const d = err?.error?.detail;
          this.trainError = typeof d === 'string' ? d : d?.message || 'Training failed.';
          this.loadRuns();
        }
      });
  }

  private stopTimer(): void {
    this.training = false;
    clearInterval(this.timer);
  }

  // ---------------------------------------------------------------- runs

  loadRuns(select: number | null = null): void {
    this.runsLoading = true;
    this.service.runs().subscribe({
      next: (runs) => {
        this.runs = runs;
        this.runsLoading = false;
        const id = select ?? this.run?.run_id ?? runs.find((r) => r.status === 'COMPLETED')?.run_id ?? null;
        if (id) {
          this.openRun(id);
        } else {
          this.run = null;
        }
      },
      error: () => (this.runsLoading = false)
    });
  }

  openRun(id: number): void {
    this.runLoading = true;
    this.router.navigate([], { relativeTo: this.route, queryParams: { run: id }, replaceUrl: true });
    this.service.run(id).subscribe({
      next: (run) => {
        this.run = run;
        this.runLoading = false;
        const imp = Object.keys(run.results?.importance ?? {});
        this.importanceModel = imp.includes(this.importanceModel) ? this.importanceModel : imp[0] ?? '';
        this.buildCharts();
        this.peakRows = [];
        this.peakChart = undefined;
        if (run.status === 'COMPLETED' && run.mp_ids.length) {
          this.service.peaks(run.run_id, run.mp_ids[0]).subscribe((rows) => {
            this.peakRows = rows;
            this.buildPeakChart();
          });
        }
      },
      error: () => (this.runLoading = false)
    });
  }

  makeDefaultRun(r: NfRun, event?: Event): void {
    event?.stopPropagation();
    this.service.makeDefault(r.run_id).subscribe(() => this.loadRuns(this.run?.run_id ?? null));
  }

  deleteRun(r: NfRun, event: Event): void {
    event.stopPropagation();
    if (!window.confirm(`Delete net-load forecast run #${r.run_id}, its scores and backtests?`)) {
      return;
    }
    this.service.deleteRun(r.run_id).subscribe(() => {
      if (this.run?.run_id === r.run_id) {
        this.run = null;
      }
      this.loadRuns();
    });
  }

  reuse(r: NfRunDetail): void {
    this.mpIds = new Set(r.mp_ids);
    this.dateFrom = r.date_from ?? '';
    this.dateTo = r.date_to ?? '';
    this.groups = new Set(r.feature_groups);
    this.weatherSource = r.weather_source;
    this.threshold = r.results?.threshold.given ? r.peak_threshold_kw : null;
    this.chosen = new Set(r.models);
    this.horizon = r.horizon_hours;
    this.testPct = r.test_fraction * 100;
    this.originStep = r.origin_step_h;
    this.trainStep = r.params['train_origin_step_h'] ?? 2;
    for (const k of r.models) {
      if (r.params[k]) {
        this.params[k] = { ...r.params[k] };
      }
    }
    this.runName = '';
    this.schedulePreview();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  // ---------------------------------------------------------------- scores

  get modelKeys(): NfRegressorKey[] {
    return NF_ORDER.filter((k) => this.run?.metrics?.[k]);
  }

  get peakKeys(): NfModelKey[] {
    const keys: NfModelKey[] = [...this.modelKeys];
    if (this.run?.metrics?.peak_classifier) {
      keys.push('peak_classifier');
    }
    return keys;
  }

  private value(k: NfModelKey, c: ScoreCol): number | null {
    const v = this.run?.metrics?.[k]?.[c.key];
    return typeof v === 'number' && Number.isFinite(v) ? v * (c.scale ?? 1) : null;
  }

  cell(k: NfModelKey, c: ScoreCol): string {
    const v = this.value(k, c);
    return v === null ? '—' : v.toFixed(c.digits);
  }

  refCell(c: ScoreCol): string {
    const v = this.run?.results?.classifier?.reference?.[c.key];
    return typeof v === 'number' && Number.isFinite(v) ? (v * (c.scale ?? 1)).toFixed(c.digits) : '—';
  }

  isBest(k: NfModelKey, c: ScoreCol, keys: NfModelKey[]): boolean {
    const vals = keys.map((x) => [x, this.value(x, c)] as const).filter(([, v]) => v !== null) as [NfModelKey, number][];
    if (vals.length < 2) {
      return false;
    }
    const rank = (v: number) => (c.better === 'low' ? v : c.better === 'high' ? -v : c.better === 'zero' ? Math.abs(v) : Math.abs(v - 80));
    return vals.reduce((b, x) => (rank(x[1]) < rank(b[1]) ? x : b))[0] === k;
  }

  timing(k: string): string {
    const v = this.run?.results?.timings_ms[k as NfModelKey];
    return v === undefined ? '' : v < 1000 ? `${v} ms` : `${(v / 1000).toFixed(1)} s`;
  }

  window(r: NfRun): string {
    return `${r.date_from ?? 'start'} → ${r.date_to ?? 'end'}`;
  }

  duration(ms: number | null): string {
    return ms === null ? '' : ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
  }

  plantTime(ts: string | null | undefined): string {
    return ts ? ts.replace('T', ' ').slice(0, 16) : '—';
  }

  num(v: number | null | undefined, d = 1): string {
    return typeof v === 'number' && Number.isFinite(v) ? v.toFixed(d) : '—';
  }

  hours(w: number[] | undefined): string {
    if (!w || w.length < 2) {
      return '—';
    }
    const f = (h: number) => `${String(Math.floor(h)).padStart(2, '0')}:${String(Math.round((h % 1) * 60)).padStart(2, '0')}`;
    return `${f(w[0])}–${f(w[1])}`;
  }

  get splitRows(): { mp: string; s: { train_to: string; test_from: string; test_to: string } }[] {
    return Object.entries(this.run?.results?.split ?? {}).map(([mp, s]) => ({ mp, s }));
  }

  get calRows(): { k: NfModelKey; c: { n: number; days?: number; median?: number; q10?: number; q90?: number } }[] {
    return this.modelKeys
      .filter((k) => k !== 'seasonal_naive')
      .map((k) => ({ k: k as NfModelKey, c: this.run?.results?.peak_calibration?.[k] ?? { n: 0 } }));
  }

  get coefRows(): { f: string; v: number }[] {
    return Object.entries(this.run?.results?.classifier?.coefficients ?? {})
      .map(([f, v]) => ({ f, v }))
      .sort((a, b) => Math.abs(b.v) - Math.abs(a.v));
  }

  modelName(k: string): string {
    return NF_LABELS[k as NfModelKey] ?? k;
  }

  get importanceModels(): string[] {
    return Object.keys(this.run?.results?.importance ?? {});
  }

  // ---------------------------------------------------------------- charts

  buildCharts(): void {
    this.buildLead();
    this.buildHour();
    this.buildImportance();
  }

  private lineChart(series: Partial<Record<string, (number | null)[]>> | undefined, labels: (string | number)[],
                    xTitle: string, title: (l: string) => string): AnyConfig | undefined {
    if (!series) {
      return undefined;
    }
    return {
      type: 'line',
      data: {
        labels,
        datasets: this.modelKeys.map((k) => ({
          label: NF_LABELS[k],
          data: series[k] ?? [],
          borderColor: NF_COLORS[k],
          backgroundColor: NF_COLORS[k],
          borderDash: NF_DASH[k],
          borderWidth: k === this.run?.best_model ? 3 : 2,
          pointRadius: 0,
          tension: 0.25,
          spanGaps: true
        }))
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: legend(),
          tooltip: {
            ...tooltip,
            callbacks: {
              title: (items: TooltipItem<'line'>[]) => title(String(items[0]?.label)),
              label: (ctx: TooltipItem<'line'>) => `${ctx.dataset.label}: ${(ctx.parsed.y as number)?.toFixed(1)} kW`
            }
          }
        },
        scales: { x: axis(xTitle, { ticks: { color: '#6b6f76', maxTicksLimit: 13 } }), y: axis('MAE (kW)', { beginAtZero: true }) }
      }
    } as AnyConfig;
  }

  private buildLead(): void {
    const H = this.run?.horizon_hours ?? 0;
    this.leadChart = this.lineChart(this.run?.results?.mae_by_lead, Array.from({ length: H }, (_, i) => i + 1), 'Hours ahead', (l) => `${l} h ahead`);
  }

  private buildHour(): void {
    this.hourChart = this.lineChart(this.run?.results?.mae_by_hour, Array.from({ length: 24 }, (_, i) => i), 'Hour of day (plant time)', (l) => `${String(l).padStart(2, '0')}:00–${String(Number(l) + 1).padStart(2, '0')}:00`);
  }

  /** Day-ahead peaks: per test day, each model's forecast from the origin whose lead to the window is closest to
   *  24 h, against the actual peak and the threshold. */
  buildPeakChart(): void {
    const rows = this.peakRows.filter((r) => r.model !== 'peak_classifier' && r.p50 !== null);
    if (!rows.length) {
      this.peakChart = undefined;
      return;
    }
    const days = Array.from(new Set(rows.map((r) => r.target_date))).sort();
    const pick = (k: NfModelKey, d: string) =>
      rows.filter((r) => r.model === k && r.target_date === d).reduce<NfPeak | null>((b, r) => (!b || Math.abs((r.lead_h ?? 0) - 24) < Math.abs((b.lead_h ?? 0) - 24) ? r : b), null);
    const actual = days.map((d) => rows.find((r) => r.target_date === d)?.actual ?? null);
    const thr = this.run?.peak_threshold_kw ?? null;
    this.peakChart = {
      type: 'bar',
      data: {
        labels: days.map((d) => d.slice(5)),
        datasets: [
          { type: 'bar', label: 'Actual peak', data: actual, backgroundColor: 'rgba(30, 35, 42, 0.18)', borderColor: '#1e232a', borderWidth: 1, borderRadius: 3, barPercentage: 0.7, order: 5 } as any,
          ...this.modelKeys.map((k) => ({
            type: 'line',
            label: `${NF_LABELS[k]} P50`,
            data: days.map((d) => pick(k, d)?.p50 ?? null),
            borderColor: NF_COLORS[k],
            backgroundColor: NF_COLORS[k],
            borderDash: NF_DASH[k],
            borderWidth: 2,
            pointRadius: 4,
            pointHoverRadius: 6,
            order: 1
          })),
          ...(thr ? [{ type: 'line', label: `Threshold ${thr} kW`, data: days.map(() => thr), borderColor: THRESHOLD, borderDash: [6, 4], borderWidth: 1.4, pointRadius: 0, order: 2 } as any] : [])
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: legend(),
          tooltip: { ...tooltip, callbacks: { label: (ctx: TooltipItem<'bar'>) => `${ctx.dataset.label}: ${Number(ctx.parsed.y).toFixed(0)} kW` } }
        },
        scales: {
          x: axis('Test day (forecast ≈ 1 day ahead)', { grid: { display: false } }),
          y: axis('Billing-window peak (kW)', { suggestedMin: Math.min(...(actual.filter((v) => v !== null) as number[])) * 0.85 })
        }
      }
    } as AnyConfig;
  }

  buildImportance(): void {
    const imp = this.run?.results?.importance?.[this.importanceModel as NfModelKey];
    if (!imp) {
      this.importanceChart = undefined;
      return;
    }
    const entries = Object.entries(imp)
      .filter(([, v]) => v > 0.002)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 18);
    this.importanceHeight = Math.max(160, entries.length * 22 + 40);
    const color = NF_COLORS[this.importanceModel as NfModelKey] ?? '#475569';
    const isClf = this.importanceModel === 'peak_classifier';
    this.importanceChart = {
      type: 'bar',
      data: { labels: entries.map(([f]) => f), datasets: [{ data: entries.map(([, v]) => v * 100), backgroundColor: color, borderRadius: 4, barThickness: 12 }] },
      options: {
        indexAxis: 'y',
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        layout: { padding: { right: 44 } },
        plugins: {
          legend: { display: false },
          tooltip: { ...tooltip, callbacks: { label: (ctx: TooltipItem<'bar'>) => `${(ctx.parsed.x as number).toFixed(1)} % of ${isClf ? '|coefficient|' : 'gain'}` } },
          valueLabels: { format: (v: number) => `${v.toFixed(1)} %` }
        } as any,
        scales: { x: axis(isClf ? 'Share of |standardised coefficient| (%)' : 'Share of split gain (%)'), y: axis(undefined, { grid: { display: false } }) }
      }
    } as AnyConfig;
  }
}
