import { CommonModule } from '@angular/common';
import { Component, OnDestroy, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { TooltipItem } from 'chart.js';

import { RulChemParams, RulMethod, RulOptions, RulRun, RulRunDetail, RulScores, RulSystem } from '../../../core/models/rul.model';
import { RulService } from '../../../core/services/rul.service';
import { ChartCanvasComponent } from '../../telemetry/graphs/chart-canvas.component';
import { AnyConfig, axis, legend, tooltip } from '../price-forecast-shared/pf-charts';
import { R_COLORS, R_DASH, R_LABELS, R_ORDER } from '../rul-shared/rul-charts';

type ImportanceKey = 'rsf_importance' | 'gbm_importance' | 'hybrid_importance';

/** ML Model -> RUL Model: build the remaining-useful-life models (physics fade curve, LightGBM, hybrid, Cox, RSF) on
 *  the fleet's aging data, validated leave-one-unit-out with censoring-aware scores. */
@Component({
  selector: 'app-rul-model',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink, ChartCanvasComponent],
  templateUrl: './rul-model.component.html',
  styleUrls: [
    '../model-training/model-training.component.scss',
    '../price-forecast-model/price-forecast-model.component.scss',
    '../thermal-forecast-model/thermal-forecast-model.component.scss',
    '../aux-forecast-model/aux-forecast-model.component.scss',
    './rul-model.component.scss'
  ]
})
export class RulModelComponent implements OnInit, OnDestroy {
  readonly colors = R_COLORS;
  readonly labels = R_LABELS;
  readonly order = R_ORDER;
  readonly Math = Math;

  options: RulOptions | null = null;
  optionsError: string | null = null;
  systemIds = new Set<number>();
  methods = new Set<RulMethod>(R_ORDER);
  groups = new Set<string>();
  failuresAs: 'event' | 'censored' = 'event';
  arrhenius = true;
  knee = true;
  calibrate = true;
  physics: Record<string, number> = {};
  gbm: Record<string, number> = {};
  survival: Record<string, number> = {};
  showGbm = false;
  showSurvival = false;
  runName = '';
  makeDefault = true;

  training = false;
  trainError: string | null = null;
  elapsed = 0;
  private timer?: ReturnType<typeof setInterval>;

  runs: RulRun[] = [];
  runsLoading = true;
  run: RulRunDetail | null = null;
  runLoading = false;
  chemistry = '';
  importanceKey: ImportanceKey = 'rsf_importance';
  lifeChart?: AnyConfig;
  kneeChart?: AnyConfig;
  importanceChart?: AnyConfig;
  importanceHeight = 260;

  constructor(private service: RulService, private route: ActivatedRoute, private router: Router) {}

  ngOnInit(): void {
    this.service.options().subscribe({
      next: (o) => {
        this.options = o;
        this.systemIds = new Set(o.systems.filter((s) => s.snapshots > 0).map((s) => s.system_id));
        this.groups = new Set(Object.keys(o.feature_groups));
        this.physics = Object.fromEntries(o.physics_params.map((p) => [p.name, p.default]));
        this.gbm = Object.fromEntries(o.gbm_params.map((p) => [p.name, p.default]));
        this.survival = Object.fromEntries(o.survival_params.map((p) => [p.name, p.default]));
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

  toggle<T>(set: Set<T>, v: T): Set<T> {
    const out = new Set(set);
    out.has(v) ? out.delete(v) : out.add(v);
    return out;
  }

  toggleSystem(s: RulSystem): void {
    if (s.snapshots) {
      this.systemIds = this.toggle(this.systemIds, s.system_id);
    }
  }

  get eolList(): { chemistry: string; text: string }[] {
    return Object.entries(this.options?.eol_criteria ?? {}).map(([c, e]) => ({
      chemistry: c,
      text: `SOH < ${e.soh_eol_pct} %${e.resistance_eol_pct ? ` or R > ${e.resistance_eol_pct / 100}× BOL` : ''}`
    }));
  }

  get selectionStats() {
    const s = (this.options?.systems ?? []).filter((x) => this.systemIds.has(x.system_id));
    return { units: s.length, retired: s.filter((x) => x.retired).length, failed: s.filter((x) => (x.end_events ?? '').includes('FAILURE')).length };
  }

  get problem(): string | null {
    const st = this.selectionStats;
    if (st.units < 4) {
      return 'Choose at least 4 units';
    }
    if (st.retired < 2) {
      return 'Choose at least 2 retired units (they carry the true RUL labels)';
    }
    if (!this.methods.size) {
      return 'Choose at least one method';
    }
    if (!this.groups.size) {
      return 'Choose at least one feature group';
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
    const all = (this.options?.systems ?? []).filter((s) => s.snapshots > 0).length === this.systemIds.size;
    this.service
      .train({
        system_ids: all ? null : Array.from(this.systemIds),
        methods: R_ORDER.filter((m) => this.methods.has(m)),
        feature_groups: Array.from(this.groups),
        failures_as: this.failuresAs,
        arrhenius: this.arrhenius,
        knee: this.knee,
        calibrate_bands: this.calibrate,
        physics: this.physics,
        gbm: this.gbm,
        survival: this.survival,
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
        const chems = Object.keys(run.results?.params ?? {});
        if (!chems.includes(this.chemistry)) {
          this.chemistry = chems[0] ?? '';
        }
        if (!this.chemParams?.[this.importanceKey]) {
          this.importanceKey = (['rsf_importance', 'hybrid_importance', 'gbm_importance'] as ImportanceKey[]).find((k) => this.chemParams?.[k]) ?? 'rsf_importance';
        }
        this.buildCharts();
      },
      error: () => (this.runLoading = false)
    });
  }

  makeDefaultRun(r: RulRun, event?: Event): void {
    event?.stopPropagation();
    this.service.makeDefault(r.run_id).subscribe(() => this.loadRuns(this.run?.run_id ?? null));
  }

  deleteRun(r: RulRun, event: Event): void {
    event.stopPropagation();
    if (!window.confirm(`Delete RUL run #${r.run_id}, its scores, backtest and forecasts?`)) {
      return;
    }
    this.service.deleteRun(r.run_id).subscribe(() => {
      if (this.run?.run_id === r.run_id) {
        this.run = null;
      }
      this.loadRuns();
    });
  }

  reuse(r: RulRunDetail): void {
    const p = r.params;
    this.systemIds = r.system_ids?.length ? new Set(r.system_ids) : new Set((this.options?.systems ?? []).filter((s) => s.snapshots > 0).map((s) => s.system_id));
    this.methods = new Set(r.methods);
    this.groups = new Set(p['feature_groups'] ?? Object.keys(this.options?.feature_groups ?? {}));
    this.failuresAs = p['failures_as'] ?? 'event';
    this.arrhenius = p['arrhenius'] ?? true;
    this.knee = p['knee'] ?? true;
    this.calibrate = p['calibrate_bands'] ?? true;
    this.physics = { ...this.physics, ...(p['physics'] ?? {}) };
    this.gbm = { ...this.gbm, ...(p['gbm'] ?? {}) };
    this.survival = { ...this.survival, ...(p['survival'] ?? {}) };
    this.runName = '';
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  // ---------------------------------------------------------------- scores

  s(m: RulMethod, scope = 'all'): RulScores | undefined {
    return this.run?.metrics?.[m]?.[scope];
  }

  get runMethods(): RulMethod[] {
    return R_ORDER.filter((m) => this.run?.methods.includes(m) && this.run?.metrics?.[m]);
  }

  /** The best method on a score: closest to 80 % for coverage, closest to 0 for bias, else lowest (highest for the
   *  C-index). */
  best(key: keyof RulScores, scope = 'all'): RulMethod | null {
    const cost = (v: number) =>
      key === 'coverage_pct' ? Math.abs(v - 80) : key === 'bias_days' ? Math.abs(v) : key === 'c_index' ? -v : v;
    let best: RulMethod | null = null;
    let bc = Infinity;
    for (const m of this.runMethods) {
      const v = this.s(m, scope)?.[key];
      if (typeof v === 'number' && cost(v) < bc) {
        bc = cost(v);
        best = m;
      }
    }
    return best;
  }

  get units() {
    return this.run?.results?.units ?? [];
  }

  unitScore(m: RulMethod, code: string): RulScores | undefined {
    return this.s(m, `unit:${code}`);
  }

  get chemistries(): string[] {
    return Object.keys(this.run?.results?.params ?? {});
  }

  get chemParams(): RulChemParams | null {
    return this.run?.results?.params?.[this.chemistry] ?? null;
  }

  get coxRows() {
    return Object.entries(this.chemParams?.cox ?? {}).map(([k, v]) => ({ feature: k, ...v }));
  }

  batchRows(p: RulChemParams) {
    const ph = p.physics;
    if (!ph) {
      return [];
    }
    return Object.keys(ph.batch_capacity_factor).map((b) => ({ batch: b, cap: ph.batch_capacity_factor[b], res: ph.batch_resistance_factor?.[b] ?? null }));
  }

  num(v: number | null | undefined, d = 0): string {
    return typeof v === 'number' && Number.isFinite(v) ? v.toFixed(d) : '—';
  }

  signed(v: number | null | undefined, d = 0): string {
    return typeof v === 'number' && Number.isFinite(v) ? `${v > 0 ? '+' : ''}${v.toFixed(d)}` : '—';
  }

  duration(ms: number | null): string {
    return ms === null ? '' : ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
  }

  shortSystems(r: RulRun): string {
    return r.system_ids?.length ? `${r.system_ids.length} units` : 'all units';
  }

  setChemistry(c: string): void {
    this.chemistry = c;
    this.buildCharts();
  }

  setImportance(k: ImportanceKey): void {
    this.importanceKey = k;
    this.buildCharts();
  }

  // ---------------------------------------------------------------- charts

  buildCharts(): void {
    const buckets = this.options?.life_buckets ?? ['0-25 %', '25-50 %', '50-75 %', '75-100 %'];
    const methods = this.runMethods;
    this.lifeChart = methods.length
      ? ({
          type: 'line',
          data: {
            labels: buckets.map((b) => `${b} of life`),
            datasets: methods.map((m) => ({
              label: R_LABELS[m],
              data: buckets.map((b) => this.s(m, `life:${b}`)?.mae_days ?? null),
              borderColor: R_COLORS[m],
              backgroundColor: R_COLORS[m],
              borderDash: R_DASH[m],
              borderWidth: m === 'physics' || m === 'hybrid' ? 3 : 2,
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
              tooltip: { ...tooltip, callbacks: { label: (ctx: TooltipItem<'line'>) => `${ctx.dataset.label}: ${Math.round(ctx.parsed.y as number)} days` } }
            },
            scales: { x: axis('Where in its life the unit was when predicted'), y: axis('MAE (days)', { beginAtZero: true }) }
          }
        } as AnyConfig)
      : undefined;
    const ph = this.chemParams?.physics;
    this.kneeChart = ph?.knee_bands?.length
      ? ({
          type: 'bar',
          data: {
            labels: ph.knee_bands.map((b) => `SOH ${b}`),
            datasets: [
              { label: 'Capacity fade', data: ph.knee_capacity, backgroundColor: R_COLORS.physics, borderRadius: 3, maxBarThickness: 18 },
              { label: 'Resistance rise', data: ph.knee_resistance, backgroundColor: '#9bbfe9', borderRadius: 3, maxBarThickness: 18 }
            ]
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
              legend: legend(),
              tooltip: { ...tooltip, callbacks: { label: (ctx: TooltipItem<'bar'>) => `${ctx.dataset.label}: ×${(ctx.parsed.y as number).toFixed(2)} the smooth curve` } }
            },
            scales: { x: axis(undefined, { grid: { display: false } }), y: axis('Acceleration (× curve)', { beginAtZero: true }) }
          }
        } as AnyConfig)
      : undefined;
    const imp = this.chemParams?.[this.importanceKey];
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
      data: { labels: entries.map(([f]) => f), datasets: [{ data: entries.map(([, v]) => v * 100), backgroundColor: R_COLORS.hybrid, borderRadius: 4, barThickness: 12 }] },
      options: {
        indexAxis: 'y',
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        layout: { padding: { right: 44 } },
        plugins: {
          legend: { display: false },
          tooltip: { ...tooltip, callbacks: { label: (ctx: TooltipItem<'bar'>) => `${(ctx.parsed.x as number).toFixed(1)} %` } },
          valueLabels: { format: (v: number) => `${v.toFixed(1)} %` }
        } as any,
        scales: { x: axis(this.importanceKey === 'rsf_importance' ? 'Share of log-rank split gain (%)' : 'Share of split gain (%)'), y: axis(undefined, { grid: { display: false } }) }
      }
    } as AnyConfig;
  }
}
