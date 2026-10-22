import { CommonModule } from '@angular/common';
import { Component, OnDestroy, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { TooltipItem } from 'chart.js';

import {
  ThermalMethod,
  ThermalOptions,
  ThermalRun,
  ThermalRunDetail,
  ThermalScores,
  ThermalSystem,
  ThermalTarget,
  ThermalTargetSpec
} from '../../../core/models/thermal-forecast.model';
import { ThermalForecastService } from '../../../core/services/thermal-forecast.service';
import { ChartCanvasComponent } from '../../telemetry/graphs/chart-canvas.component';
import { AnyConfig, axis, legend, tooltip } from '../price-forecast-shared/pf-charts';
import { T_COLORS, T_DASH, T_LABELS, T_ORDER } from '../thermal-forecast-shared/thermal-charts';

const HORIZON_CHOICES = [5, 10, 15, 30, 45, 60, 90, 120];

/** ML Model -> Temperature Forecast: build the cell / IGBT / coolant / enclosure temperature forecasters (RC grey-box
 *  + LightGBM residual quantiles) and compare them with persistence and seasonal naïve, incl. exceedance recall. */
@Component({
  selector: 'app-thermal-forecast-model',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink, ChartCanvasComponent],
  templateUrl: './thermal-forecast-model.component.html',
  styleUrls: ['../model-training/model-training.component.scss', '../price-forecast-model/price-forecast-model.component.scss', './thermal-forecast-model.component.scss']
})
export class ThermalForecastModelComponent implements OnInit, OnDestroy {
  readonly colors = T_COLORS;
  readonly labels = T_LABELS;
  readonly methods = T_ORDER;
  readonly horizonChoices = HORIZON_CHOICES;

  options: ThermalOptions | null = null;
  optionsError: string | null = null;
  systemIds = new Set<number>();
  dateFrom = '';
  dateTo = '';
  targets = new Set<ThermalTarget>();
  horizons = new Set<number>([5, 15, 30, 60]);
  thresholds: Record<string, number> = {};
  planSource: 'scheduled' | 'typical' = 'scheduled';
  testPct = 20;
  trainStep = 2;
  gbm: Record<string, number> = {};
  showGbm = false;
  runName = '';
  makeDefault = true;

  training = false;
  trainError: string | null = null;
  elapsed = 0;
  private timer?: ReturnType<typeof setInterval>;

  runs: ThermalRun[] = [];
  runsLoading = true;
  run: ThermalRunDetail | null = null;
  runLoading = false;
  target: ThermalTarget = 'cell_temp_max_c';
  maeChart?: AnyConfig;
  importanceChart?: AnyConfig;
  importanceHeight = 300;

  constructor(private service: ThermalForecastService, private route: ActivatedRoute, private router: Router) {}

  ngOnInit(): void {
    this.service.options().subscribe({
      next: (o) => {
        this.options = o;
        this.systemIds = new Set(o.systems.filter((s) => s.readings > 0).map((s) => s.battery_system_id));
        this.targets = new Set(o.targets.map((t) => t.key));
        this.horizons = new Set(o.defaults.horizons_min);
        this.thresholds = Object.fromEntries(o.targets.map((t) => [t.key, t.threshold]));
        this.testPct = o.defaults.test_fraction * 100;
        this.trainStep = o.defaults.train_origin_step;
        this.gbm = Object.fromEntries(o.gbm_params.map((p) => [p.name, p.default]));
      },
      error: (err) =>
        (this.optionsError = err?.status === 0 ? 'Could not reach the ML service. Is it running on port 8100?' : 'Could not load the options.')
    });
    this.loadRuns(Number(this.route.snapshot.queryParamMap.get('run')) || null);
  }

  ngOnDestroy(): void {
    clearInterval(this.timer);
  }

  // ---------------------------------------------------------------- inputs

  systemLabel(s: ThermalSystem): string {
    return `${s.site_name ?? s.system_name ?? 'System ' + s.battery_system_id} · ${s.system_name ?? ''}`;
  }

  shortSystem(id: number | string): string {
    const s = this.options?.systems.find((x) => x.battery_system_id === Number(id));
    return s?.site_name?.replace(/ BESS Site| Grid Storage Site| Site/, '') ?? `System ${id}`;
  }

  toggle<T>(set: Set<T>, v: T): Set<T> {
    const out = new Set(set);
    out.has(v) ? out.delete(v) : out.add(v);
    return out;
  }

  toggleSystem(s: ThermalSystem): void {
    if (s.readings) {
      this.systemIds = this.toggle(this.systemIds, s.battery_system_id);
    }
  }

  toggleTarget(t: ThermalTarget): void {
    this.targets = this.toggle(this.targets, t);
  }

  toggleHorizon(h: number): void {
    this.horizons = this.toggle(this.horizons, h);
  }

  catalog(t: string): number | null {
    return this.options?.catalog_thresholds[t] ?? null;
  }

  familyLabel(f: string): string {
    return this.options?.families[f] ?? f;
  }

  get problem(): string | null {
    if (!this.systemIds.size) {
      return 'Choose at least one battery system';
    }
    if (!this.targets.size) {
      return 'Choose at least one target';
    }
    if (!this.horizons.size) {
      return 'Choose at least one horizon';
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
    const targets = Array.from(this.targets);
    this.service
      .train({
        system_ids: Array.from(this.systemIds),
        date_from: this.dateFrom || null,
        date_to: this.dateTo || null,
        targets,
        horizons_min: Array.from(this.horizons).sort((a, b) => a - b),
        thresholds: Object.fromEntries(targets.map((t) => [t, Number(this.thresholds[t])])),
        plan_source: this.planSource,
        test_fraction: Number(this.testPct) / 100,
        train_origin_step: Number(this.trainStep),
        gbm_params: this.gbm,
        run_name: this.runName.trim() || null,
        make_default: this.makeDefault
      })
      .subscribe({
        next: (run) => {
          this.stop();
          this.loadRuns(run.run_id);
        },
        error: (err) => {
          this.stop();
          const d = err?.error?.detail;
          this.trainError = typeof d === 'string' ? d : d?.message || 'Training failed.';
          this.loadRuns();
        }
      });
  }

  private stop(): void {
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
        if (!run.targets.includes(this.target)) {
          this.target = run.targets[0];
        }
        this.buildCharts();
      },
      error: () => (this.runLoading = false)
    });
  }

  makeDefaultRun(r: ThermalRun, event?: Event): void {
    event?.stopPropagation();
    this.service.makeDefault(r.run_id).subscribe(() => this.loadRuns(this.run?.run_id ?? null));
  }

  deleteRun(r: ThermalRun, event: Event): void {
    event.stopPropagation();
    if (!window.confirm(`Delete temperature forecast run #${r.run_id}, its scores and backtests?`)) {
      return;
    }
    this.service.deleteRun(r.run_id).subscribe(() => {
      if (this.run?.run_id === r.run_id) {
        this.run = null;
      }
      this.loadRuns();
    });
  }

  reuse(r: ThermalRunDetail): void {
    this.systemIds = new Set(r.system_ids);
    this.dateFrom = r.date_from ?? '';
    this.dateTo = r.date_to ?? '';
    this.targets = new Set(r.targets);
    this.horizons = new Set(r.horizons_min);
    this.thresholds = { ...this.thresholds, ...(r.results?.thresholds ?? {}) };
    this.planSource = r.params['plan_source'] ?? 'scheduled';
    this.trainStep = r.params['train_origin_step'] ?? 2;
    this.testPct = r.test_fraction * 100;
    this.gbm = { ...(r.params['gbm'] ?? this.gbm) };
    this.runName = '';
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  // ---------------------------------------------------------------- scores

  targetLabel(t: string): string {
    return this.options?.targets.find((x) => x.key === t)?.label ?? t;
  }

  targetSpec(t: string): ThermalTargetSpec | undefined {
    return this.options?.targets.find((x) => x.key === t);
  }

  get runHorizons(): string[] {
    return Object.keys(this.run?.metrics?.[this.target] ?? {}).sort((a, b) => Number(a) - Number(b));
  }

  s(h: string, m: ThermalMethod): ThermalScores | undefined {
    return this.run?.metrics?.[this.target]?.[h]?.[m];
  }

  num(v: number | null | undefined, d = 2): string {
    return typeof v === 'number' && Number.isFinite(v) ? v.toFixed(d) : '—';
  }

  pct(v: number | null | undefined): string {
    return typeof v === 'number' && Number.isFinite(v) ? `${Math.round(v * 100)} %` : '—';
  }

  bestMae(h: string, m: ThermalMethod): boolean {
    const vals = this.methods.map((x) => this.s(h, x)?.mae).filter((v): v is number => typeof v === 'number');
    const v = this.s(h, m)?.mae;
    return typeof v === 'number' && v === Math.min(...vals);
  }

  bestPinball(h: string, m: ThermalMethod): boolean {
    const vals = this.methods.map((x) => this.s(h, x)?.pinball).filter((v): v is number => typeof v === 'number');
    const v = this.s(h, m)?.pinball;
    return typeof v === 'number' && v === Math.min(...vals);
  }

  bestRecall(h: string, m: ThermalMethod): boolean {
    const vals = this.methods.map((x) => this.s(h, x)?.recall_p90).filter((v): v is number => typeof v === 'number');
    const v = this.s(h, m)?.recall_p90;
    return typeof v === 'number' && vals.length > 0 && v === Math.max(...vals);
  }

  get rcRows(): { system: string; rc: any }[] {
    const rc = this.run?.results?.rc ?? {};
    return Object.entries(rc)
      .filter(([, v]) => v[this.target])
      .map(([system, v]) => ({ system, rc: v[this.target] }));
  }

  coefEntries(rc: any): string {
    return Object.entries(rc.coef as Record<string, number>)
      .map(([k, v]) => `${k} ${v.toFixed(Math.abs(v) < 0.01 ? 4 : 2)}`)
      .join(' · ');
  }

  window(r: ThermalRun): string {
    return `${r.date_from ?? 'start'} → ${r.date_to ?? 'end'}`;
  }

  duration(ms: number | null): string {
    return ms === null ? '' : ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
  }

  headlineMae(r: ThermalRun, t: string, m: ThermalMethod): string {
    const hs = Object.keys(r.metrics?.[t] ?? {}).map(Number);
    if (!hs.length) {
      return '—';
    }
    return this.num(r.metrics?.[t]?.[String(Math.max(...hs))]?.[m]?.mae);
  }

  setTarget(t: ThermalTarget): void {
    this.target = t;
    this.buildCharts();
  }

  // ---------------------------------------------------------------- charts

  buildCharts(): void {
    const hs = this.runHorizons;
    if (!hs.length) {
      this.maeChart = undefined;
    } else {
      this.maeChart = {
        type: 'line',
        data: {
          labels: hs.map((h) => `${h} min`),
          datasets: this.methods.map((m) => ({
            label: T_LABELS[m],
            data: hs.map((h) => this.s(h, m)?.mae ?? null),
            borderColor: T_COLORS[m],
            backgroundColor: T_COLORS[m],
            borderDash: T_DASH[m],
            borderWidth: m === 'hybrid' ? 3 : 2,
            pointRadius: 4
          }))
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          animation: false,
          interaction: { mode: 'index', intersect: false },
          plugins: {
            legend: legend(),
            tooltip: { ...tooltip, callbacks: { label: (ctx: TooltipItem<'line'>) => `${ctx.dataset.label}: ${(ctx.parsed.y as number)?.toFixed(2)} °C` } }
          },
          scales: { x: axis('Horizon'), y: axis('MAE (°C)', { beginAtZero: true }) }
        }
      } as AnyConfig;
    }
    const imp = this.run?.results?.importance?.[this.target];
    if (!imp) {
      this.importanceChart = undefined;
      return;
    }
    const entries = Object.entries(imp)
      .filter(([, v]) => v > 0.003)
      .sort((a, b) => b[1] - a[1]);
    this.importanceHeight = Math.max(160, entries.length * 22 + 40);
    this.importanceChart = {
      type: 'bar',
      data: { labels: entries.map(([f]) => f), datasets: [{ data: entries.map(([, v]) => v * 100), backgroundColor: T_COLORS.hybrid, borderRadius: 4, barThickness: 12 }] },
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
