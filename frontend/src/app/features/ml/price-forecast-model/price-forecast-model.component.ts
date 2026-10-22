import { CommonModule } from '@angular/common';
import { Component, OnDestroy, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { TooltipItem } from 'chart.js';

import {
  PfModelKey,
  PfModelSpec,
  PfOptions,
  PfPreview,
  PfRun,
  PfRunDetail,
  PfScores,
  PfUnit
} from '../../../core/models/price-forecast.model';
import { PriceForecastService } from '../../../core/services/price-forecast.service';
import { ChartCanvasComponent } from '../../telemetry/graphs/chart-canvas.component';
import { AnyConfig, PF_COLORS, PF_DASH, PF_LABELS, PF_ORDER, axis, legend, tooltip } from '../price-forecast-shared/pf-charts';

interface ScoreCol {
  key: keyof PfScores;
  label: string;
  better: 'low' | 'high' | 'target80';
  digits: number;
  help: string;
}

const SCORE_COLS: ScoreCol[] = [
  { key: 'mae', label: 'MAE', better: 'low', digits: 2, help: 'Mean absolute error of P50 ($/MWh)' },
  { key: 'rmse', label: 'RMSE', better: 'low', digits: 2, help: 'Root mean squared error of P50 ($/MWh)' },
  { key: 'smape_pct', label: 'sMAPE %', better: 'low', digits: 1, help: 'Symmetric mean absolute percentage error' },
  { key: 'pinball', label: 'Pinball', better: 'low', digits: 3, help: 'Quantile loss over P10 / P50 / P90 - scores the whole interval' },
  { key: 'coverage_pct', label: 'P10–P90 cover %', better: 'target80', digits: 1, help: 'Share of hours inside P10–P90 (80 % is right)' },
  { key: 'width_mwh', label: 'Width', better: 'low', digits: 1, help: 'Mean P90 − P10 ($/MWh): narrower is better at the right coverage' },
  { key: 'skill_mae_pct', label: 'Skill vs naïve %', better: 'high', digits: 1, help: '1 − MAE / MAE of the seasonal naïve' },
  { key: 'peak_mae', label: 'Peak MAE', better: 'low', digits: 2, help: 'MAE in the PEAK TOU band - where arbitrage value lives' },
  { key: 'spike_hour_mae', label: 'Spike-hour MAE', better: 'low', digits: 1, help: 'MAE on the hours that held a spike' },
  { key: 'spread_capture_pct', label: 'Spread capture %', better: 'high', digits: 1, help: 'Charge in the 3 cheapest / discharge in the 3 dearest forecast hours of each next 24 h: realised ÷ perfect-foresight spread' }
];

/** ML Model -> Price Forecast: configure, train and compare the electricity-price forecasters. */
@Component({
  selector: 'app-price-forecast-model',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink, ChartCanvasComponent],
  templateUrl: './price-forecast-model.component.html',
  styleUrls: ['../model-training/model-training.component.scss', './price-forecast-model.component.scss']
})
export class PriceForecastModelComponent implements OnInit, OnDestroy {
  readonly cols = SCORE_COLS;
  readonly colors = PF_COLORS;
  readonly labels = PF_LABELS;

  options: PfOptions | null = null;
  optionsError: string | null = null;

  emsIds = new Set<number>();
  dateFrom = '';
  dateTo = '';
  groups = new Set<string>();
  spikeThreshold = 150;
  chosen = new Set<PfModelKey>();
  params: Record<string, Record<string, number>> = {};
  openParams: PfModelKey | null = null;
  horizon = 48;
  testPct = 20;
  originStep = 6;
  trainStep = 2;
  runName = '';
  makeDefault = true;

  preview: PfPreview | null = null;
  previewing = false;
  training = false;
  trainError: string | null = null;
  elapsed = 0;
  private timer?: ReturnType<typeof setInterval>;
  private previewTimer?: ReturnType<typeof setTimeout>;

  runs: PfRun[] = [];
  runsLoading = true;
  run: PfRunDetail | null = null;
  runLoading = false;

  horizonChart?: AnyConfig;
  importanceChart?: AnyConfig;
  importanceHeight = 300;
  importanceModel = 'lightgbm';

  constructor(private service: PriceForecastService, private route: ActivatedRoute, private router: Router) {}

  ngOnInit(): void {
    this.service.options().subscribe({
      next: (o) => {
        this.options = o;
        this.groups = new Set(o.feature_groups.map((g) => g.key));
        this.emsIds = new Set(o.units.filter((u) => u.priced > 0).map((u) => u.ems_id));
        this.chosen = new Set(o.models.map((m) => m.key));
        this.horizon = o.defaults.horizon_hours;
        this.testPct = o.defaults.test_fraction * 100;
        this.originStep = o.defaults.origin_step_h;
        this.trainStep = o.defaults.train_origin_step_h;
        this.spikeThreshold = o.defaults.spike_threshold;
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

  unitLabel(u: PfUnit): string {
    return `${u.site_name ?? u.system_name ?? 'EMS ' + u.ems_id} · ${u.ems_code}`;
  }

  shortUnit(id: number | string): string {
    const u = this.options?.units.find((x) => x.ems_id === Number(id));
    return u?.site_name?.replace(/ BESS Site| Grid Storage Site| Site/, '') ?? `EMS ${id}`;
  }

  toggleUnit(u: PfUnit): void {
    if (!u.priced) {
      return;
    }
    this.emsIds.has(u.ems_id) ? this.emsIds.delete(u.ems_id) : this.emsIds.add(u.ems_id);
    this.emsIds = new Set(this.emsIds);
    this.schedulePreview();
  }

  toggleGroup(key: string, required: boolean): void {
    if (required) {
      return;
    }
    this.groups.has(key) ? this.groups.delete(key) : this.groups.add(key);
    this.groups = new Set(this.groups);
  }

  toggleModel(m: PfModelSpec): void {
    if (m.always) {
      return;
    }
    this.chosen.has(m.key) ? this.chosen.delete(m.key) : this.chosen.add(m.key);
    this.chosen = new Set(this.chosen);
  }

  familyLabel(f: string): string {
    return { baseline: 'Baseline', primary: 'Primary', deep: 'Deep sequence', spike: 'Spike handling' }[f] ?? f;
  }

  schedulePreview(): void {
    clearTimeout(this.previewTimer);
    this.previewTimer = setTimeout(() => this.loadPreview(), 450);
  }

  private selection() {
    return {
      ems_ids: Array.from(this.emsIds),
      date_from: this.dateFrom || null,
      date_to: this.dateTo || null,
      feature_groups: Array.from(this.groups),
      spike_threshold: Number(this.spikeThreshold)
    };
  }

  private loadPreview(): void {
    if (!this.emsIds.size) {
      this.preview = null;
      return;
    }
    this.previewing = true;
    this.service.preview(this.selection()).subscribe({
      next: (p) => {
        this.preview = p;
        this.previewing = false;
      },
      error: () => {
        this.preview = null;
        this.previewing = false;
      }
    });
  }

  get problem(): string | null {
    if (!this.emsIds.size) {
      return 'Choose at least one EMS';
    }
    const need = 168 + Number(this.horizon) + 48;
    if (this.preview && !this.preview.units.some((u) => u.hours >= need)) {
      return `No EMS has ${need} hours of prices (168 h history + horizon + test)`;
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
      },
      error: () => (this.runLoading = false)
    });
  }

  makeDefaultRun(r: PfRun, event?: Event): void {
    event?.stopPropagation();
    this.service.makeDefault(r.run_id).subscribe(() => this.loadRuns(this.run?.run_id ?? null));
  }

  deleteRun(r: PfRun, event: Event): void {
    event.stopPropagation();
    if (!window.confirm(`Delete price forecast run #${r.run_id}, its scores and backtests?`)) {
      return;
    }
    this.service.deleteRun(r.run_id).subscribe(() => {
      if (this.run?.run_id === r.run_id) {
        this.run = null;
      }
      this.loadRuns();
    });
  }

  reuse(r: PfRunDetail): void {
    this.emsIds = new Set(r.ems_ids);
    this.dateFrom = r.date_from ?? '';
    this.dateTo = r.date_to ?? '';
    this.groups = new Set(r.feature_groups);
    this.chosen = new Set(r.models);
    this.horizon = r.horizon_hours;
    this.testPct = r.test_fraction * 100;
    this.originStep = r.origin_step_h;
    this.trainStep = r.params['train_origin_step_h'] ?? 2;
    this.spikeThreshold = r.params['spike_threshold'] ?? 150;
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

  get modelKeys(): PfModelKey[] {
    return PF_ORDER.filter((k) => this.run?.metrics?.[k]);
  }

  cell(k: PfModelKey, c: ScoreCol): string {
    const v = this.run?.metrics?.[k]?.[c.key];
    return typeof v === 'number' && Number.isFinite(v) ? v.toFixed(c.digits) : '—';
  }

  isBest(k: PfModelKey, c: ScoreCol): boolean {
    const m = this.run?.metrics;
    if (!m) {
      return false;
    }
    const vals = this.modelKeys.map((x) => [x, m[x]?.[c.key]] as const).filter(([, v]) => typeof v === 'number') as [PfModelKey, number][];
    if (!vals.length) {
      return false;
    }
    const rank = (v: number) => (c.better === 'low' ? v : c.better === 'high' ? -v : Math.abs(v - 80));
    return vals.reduce((b, x) => (rank(x[1]) < rank(b[1]) ? x : b))[0] === k;
  }

  bandCell(k: PfModelKey, code: string): string {
    const v = this.run?.results?.mae_by_band[k]?.[code];
    return typeof v === 'number' ? v.toFixed(2) : '—';
  }

  bandBest(k: PfModelKey, code: string): boolean {
    const vals = this.modelKeys.map((x) => this.run?.results?.mae_by_band[x]?.[code]).filter((v): v is number => typeof v === 'number');
    const v = this.run?.results?.mae_by_band[k]?.[code];
    return typeof v === 'number' && v === Math.min(...vals);
  }

  bandName(code: string): string {
    const b = Object.values(this.run?.results?.bands ?? {})[0]?.find((x) => x.band_code === code);
    return b ? `${b.band_name} ${String(b.start_hour).padStart(2, '0')}–${String(b.end_hour).padStart(2, '0')}` : code;
  }

  timing(k: string): string {
    const v = this.run?.results?.timings_ms[k];
    return v === undefined ? '' : v < 1000 ? `${v} ms` : `${(v / 1000).toFixed(1)} s`;
  }

  window(r: PfRun): string {
    return `${r.date_from ?? 'start'} → ${r.date_to ?? 'end'}`;
  }

  duration(ms: number | null): string {
    return ms === null ? '' : ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
  }

  plantTime(ts: string | null | undefined): string {
    return ts ? ts.replace('T', ' ').slice(0, 16) : '—';
  }

  num(v: number | null | undefined, d = 2): string {
    return typeof v === 'number' && Number.isFinite(v) ? v.toFixed(d) : '—';
  }

  get splitRows(): { ems: string; s: { train_to: string; test_from: string; test_to: string } }[] {
    return Object.entries(this.run?.results?.split ?? {}).map(([ems, s]) => ({ ems, s }));
  }

  modelName(k: string): string {
    return PF_LABELS[k as PfModelKey] ?? k;
  }

  get importanceModels(): string[] {
    return Object.keys(this.run?.results?.importance ?? {});
  }

  // ---------------------------------------------------------------- charts

  buildCharts(): void {
    this.buildHorizon();
    this.buildImportance();
  }

  private buildHorizon(): void {
    const byH = this.run?.results?.mae_by_horizon;
    if (!byH) {
      this.horizonChart = undefined;
      return;
    }
    const H = this.run!.horizon_hours;
    this.horizonChart = {
      type: 'line',
      data: {
        labels: Array.from({ length: H }, (_, i) => i + 1),
        datasets: this.modelKeys.map((k) => ({
          label: PF_LABELS[k],
          data: byH[k] ?? [],
          borderColor: PF_COLORS[k],
          backgroundColor: PF_COLORS[k],
          borderDash: PF_DASH[k],
          borderWidth: k === this.run?.best_model ? 3 : 2,
          pointRadius: 0,
          tension: 0.25
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
              title: (items: TooltipItem<'line'>[]) => `${items[0]?.label} h ahead`,
              label: (ctx: TooltipItem<'line'>) => `${ctx.dataset.label}: ${(ctx.parsed.y as number)?.toFixed(2)} $/MWh`
            }
          }
        },
        scales: { x: axis('Hours ahead', { ticks: { color: '#6b6f76', maxTicksLimit: 12 } }), y: axis('MAE ($/MWh)', { beginAtZero: true }) }
      }
    } as AnyConfig;
  }

  buildImportance(): void {
    const imp = this.run?.results?.importance?.[this.importanceModel];
    if (!imp) {
      this.importanceChart = undefined;
      return;
    }
    const entries = Object.entries(imp)
      .filter(([, v]) => v > 0.002)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 18);
    this.importanceHeight = Math.max(160, entries.length * 22 + 40);
    const color = PF_COLORS[this.importanceModel as PfModelKey] ?? '#475569';
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
          tooltip: { ...tooltip, callbacks: { label: (ctx: TooltipItem<'bar'>) => `${(ctx.parsed.x as number).toFixed(1)} % of gain` } },
          valueLabels: { format: (v: number) => `${v.toFixed(1)} %` }
        } as any,
        scales: { x: axis('Share of split gain (%)'), y: axis(undefined, { grid: { display: false } }) }
      }
    } as AnyConfig;
  }
}
