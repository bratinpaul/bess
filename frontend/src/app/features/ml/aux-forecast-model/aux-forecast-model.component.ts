import { CommonModule } from '@angular/common';
import { Component, OnDestroy, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { TooltipItem } from 'chart.js';

import {
  AuxAmbientSource,
  AuxDailyScore,
  AuxGreybox,
  AuxMethod,
  AuxOptions,
  AuxPlanSource,
  AuxRun,
  AuxRunDetail,
  AuxScores,
  AuxSite
} from '../../../core/models/aux-forecast.model';
import { AuxForecastService } from '../../../core/services/aux-forecast.service';
import { ChartCanvasComponent } from '../../telemetry/graphs/chart-canvas.component';
import { A_COLORS, A_DASH, A_LABELS, A_ORDER } from '../aux-forecast-shared/aux-charts';
import { AnyConfig, axis, legend, tooltip } from '../price-forecast-shared/pf-charts';

const HORIZON_CHOICES = [1, 2, 4, 6, 12, 24];

/** ML Model -> Aux / HVAC Forecast Model: build the site's parasitic-load forecaster (grey-box heat load / COP model per
 *  site + pooled LightGBM residual quantiles) and compare it with persistence and same-time-yesterday, per horizon bucket
 *  and on the daily aux energy. */
@Component({
  selector: 'app-aux-forecast-model',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink, ChartCanvasComponent],
  templateUrl: './aux-forecast-model.component.html',
  styleUrls: [
    '../model-training/model-training.component.scss',
    '../price-forecast-model/price-forecast-model.component.scss',
    '../thermal-forecast-model/thermal-forecast-model.component.scss',
    './aux-forecast-model.component.scss'
  ]
})
export class AuxForecastModelComponent implements OnInit, OnDestroy {
  readonly colors = A_COLORS;
  readonly labels = A_LABELS;
  readonly methods = A_ORDER;
  readonly horizonChoices = HORIZON_CHOICES;
  readonly Math = Math;

  options: AuxOptions | null = null;
  optionsError: string | null = null;
  emsIds = new Set<number>();
  dateFrom = '';
  dateTo = '';
  horizonHours = 24;
  planSource: AuxPlanSource = 'scheduled';
  ambientSource: AuxAmbientSource = 'forecast';
  testPct = 20;
  trainStep = 6;
  stepsPerOrigin = 24;
  gbm: Record<string, number> = {};
  showGbm = false;
  runName = '';
  makeDefault = true;

  training = false;
  trainError: string | null = null;
  elapsed = 0;
  private timer?: ReturnType<typeof setInterval>;

  runs: AuxRun[] = [];
  runsLoading = true;
  run: AuxRunDetail | null = null;
  runLoading = false;
  scope = 'all';
  maeChart?: AnyConfig;
  importanceChart?: AnyConfig;
  importanceHeight = 300;

  constructor(private service: AuxForecastService, private route: ActivatedRoute, private router: Router) {}

  ngOnInit(): void {
    this.service.options().subscribe({
      next: (o) => {
        this.options = o;
        this.emsIds = new Set(o.sites.filter((s) => s.readings > 0).map((s) => s.ems_id));
        this.horizonHours = o.defaults.horizon_hours;
        this.planSource = o.defaults.plan_source;
        this.ambientSource = o.defaults.ambient_source;
        this.testPct = o.defaults.test_fraction * 100;
        this.trainStep = o.defaults.train_origin_step;
        this.stepsPerOrigin = o.defaults.steps_per_origin;
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

  siteLabel(s: AuxSite): string {
    return `${s.site_name ?? 'Site'} · ${s.system_name ?? s.ems_code ?? 'EMS ' + s.ems_id}`;
  }

  shortSite(id: number | string): string {
    const s = this.options?.sites.find((x) => x.ems_id === Number(id));
    return s?.site_name?.replace(/ BESS Site| Grid Storage Site| Site/, '') ?? `EMS ${id}`;
  }

  toggleSite(s: AuxSite): void {
    if (!s.readings) {
      return;
    }
    const out = new Set(this.emsIds);
    out.has(s.ems_id) ? out.delete(s.ems_id) : out.add(s.ems_id);
    this.emsIds = out;
  }

  get problem(): string | null {
    return this.emsIds.size ? null : 'Choose at least one site';
  }

  train(): void {
    if (this.problem || this.training) {
      return;
    }
    this.training = true;
    this.trainError = null;
    this.elapsed = 0;
    this.timer = setInterval(() => this.elapsed++, 1000);
    this.service
      .train({
        ems_ids: Array.from(this.emsIds),
        date_from: this.dateFrom || null,
        date_to: this.dateTo || null,
        horizon_hours: Number(this.horizonHours),
        plan_source: this.planSource,
        ambient_source: this.ambientSource,
        test_fraction: Number(this.testPct) / 100,
        train_origin_step: Number(this.trainStep),
        steps_per_origin: Number(this.stepsPerOrigin),
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
        if (this.scope !== 'all' && !run.metrics?.[this.scope]) {
          this.scope = 'all';
        }
        this.buildCharts();
      },
      error: () => (this.runLoading = false)
    });
  }

  makeDefaultRun(r: AuxRun, event?: Event): void {
    event?.stopPropagation();
    this.service.makeDefault(r.run_id).subscribe(() => this.loadRuns(this.run?.run_id ?? null));
  }

  deleteRun(r: AuxRun, event: Event): void {
    event.stopPropagation();
    if (!window.confirm(`Delete aux forecast run #${r.run_id}, its scores and backtests?`)) {
      return;
    }
    this.service.deleteRun(r.run_id).subscribe(() => {
      if (this.run?.run_id === r.run_id) {
        this.run = null;
      }
      this.loadRuns();
    });
  }

  reuse(r: AuxRunDetail): void {
    this.emsIds = new Set(r.ems_ids);
    this.dateFrom = r.date_from ?? '';
    this.dateTo = r.date_to ?? '';
    this.horizonHours = r.horizon_hours;
    this.planSource = r.params['plan_source'] ?? 'scheduled';
    this.ambientSource = r.params['ambient_source'] ?? 'forecast';
    this.trainStep = r.params['train_origin_step'] ?? 6;
    this.stepsPerOrigin = r.params['steps_per_origin'] ?? 24;
    this.testPct = r.test_fraction * 100;
    this.gbm = { ...(r.params['gbm'] ?? this.gbm) };
    this.runName = '';
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  // ---------------------------------------------------------------- scores

  get scopes(): string[] {
    return Object.keys(this.run?.metrics ?? {}).sort((a, b) => (a === 'all' ? -1 : b === 'all' ? 1 : Number(a) - Number(b)));
  }

  scopeLabel(k: string): string {
    return k === 'all' ? 'All sites' : this.shortSite(k);
  }

  get buckets(): string[] {
    const order = this.options?.buckets ?? [];
    const have = Object.keys(this.run?.metrics?.[this.scope] ?? {}).filter((b) => b !== 'all');
    return [...order.filter((b) => have.includes(b)), 'all'];
  }

  s(bucket: string, m: AuxMethod): AuxScores | undefined {
    return this.run?.metrics?.[this.scope]?.[bucket]?.[m];
  }

  daily(m: AuxMethod): AuxDailyScore | undefined {
    const d = this.run?.results?.daily as any;
    return d?.[this.scope]?.[m];
  }

  get dailyNote(): string | null {
    return (this.run?.results?.daily as any)?.note ?? null;
  }

  skill(m: AuxMethod): number | null {
    const sea = this.s('all', 'seasonal')?.mae;
    const v = this.s('all', m)?.mae;
    return typeof sea === 'number' && typeof v === 'number' && sea > 0 ? 100 * (1 - v / sea) : null;
  }

  num(v: number | null | undefined, d = 2): string {
    return typeof v === 'number' && Number.isFinite(v) ? v.toFixed(d) : '—';
  }

  signed(v: number | null | undefined, d = 1): string {
    return typeof v === 'number' && Number.isFinite(v) ? `${v > 0 ? '+' : ''}${v.toFixed(d)}` : '—';
  }

  best(bucket: string, m: AuxMethod, key: 'mae' | 'pinball'): boolean {
    const vals = this.methods.map((x) => this.s(bucket, x)?.[key]).filter((v): v is number => typeof v === 'number');
    const v = this.s(bucket, m)?.[key];
    return typeof v === 'number' && v === Math.min(...vals);
  }

  bestDaily(m: AuxMethod): boolean {
    const vals = this.methods.map((x) => this.daily(x)?.mae_kwh).filter((v): v is number => typeof v === 'number');
    const v = this.daily(m)?.mae_kwh;
    return typeof v === 'number' && v === Math.min(...vals);
  }

  get greyboxRows(): { site: string; gb: AuxGreybox }[] {
    const gb = this.run?.results?.greybox ?? {};
    return Object.entries(gb)
      .filter(([site]) => this.scope === 'all' || site === this.scope)
      .map(([site, g]) => ({ site, gb: g }));
  }

  window(r: AuxRun): string {
    return `${r.date_from ?? 'start'} → ${r.date_to ?? 'end'}`;
  }

  duration(ms: number | null): string {
    return ms === null ? '' : ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
  }

  runMae(r: AuxRun, m: AuxMethod): string {
    return this.num(r.metrics?.['all']?.['all']?.[m]?.mae);
  }

  setScope(k: string): void {
    this.scope = k;
    this.buildCharts();
  }

  // ---------------------------------------------------------------- charts

  buildCharts(): void {
    const bs = this.buckets.filter((b) => b !== 'all');
    this.maeChart = bs.length
      ? ({
          type: 'line',
          data: {
            labels: bs,
            datasets: this.methods.map((m) => ({
              label: A_LABELS[m],
              data: bs.map((b) => this.s(b, m)?.mae ?? null),
              borderColor: A_COLORS[m],
              backgroundColor: A_COLORS[m],
              borderDash: A_DASH[m],
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
              tooltip: { ...tooltip, callbacks: { label: (ctx: TooltipItem<'line'>) => `${ctx.dataset.label}: ${(ctx.parsed.y as number)?.toFixed(2)} kW` } }
            },
            scales: { x: axis('Horizon'), y: axis('MAE (kW)', { beginAtZero: true }) }
          }
        } as AnyConfig)
      : undefined;
    const imp = this.run?.results?.importance;
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
      data: { labels: entries.map(([f]) => f), datasets: [{ data: entries.map(([, v]) => v * 100), backgroundColor: A_COLORS.hybrid, borderRadius: 4, barThickness: 12 }] },
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
