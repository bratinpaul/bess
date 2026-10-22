import { CommonModule } from '@angular/common';
import { Component, OnDestroy, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { TooltipItem } from 'chart.js';

import {
  EffBooster,
  EffCycle,
  EffDirection,
  EffModelKey,
  EffOptions,
  EffParamSpec,
  EffPreview,
  EffRun,
  EffRunDetail,
  EffScores,
  EffUnitCoverage
} from '../../../core/models/efficiency.model';
import { EfficiencyService } from '../../../core/services/efficiency.service';
import { ChartCanvasComponent } from '../../telemetry/graphs/chart-canvas.component';
import {
  AnyConfig,
  INK,
  MODEL_COLORS,
  MODEL_KEYS,
  MODEL_LABELS,
  SERIES,
  axis,
  curveChart,
  fmtNum,
  fmtPct,
  hbar,
  legend,
  tooltip
} from '../efficiency-shared/eff-charts';

const RTE_COLORS = { dc: '#2a78d6', ac: '#2aa198', sys: '#d9480f' };

/** ML Model -> Efficiency: generate the PCS conversion models (grey-box, GAM, hybrid) and the cycle round-trip
 *  analysis, compare runs, pick the default the Efficiency Estimator uses. */
@Component({
  selector: 'app-efficiency-model',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink, ChartCanvasComponent],
  templateUrl: './efficiency-model.component.html',
  styleUrls: ['../model-training/model-training.component.scss', './efficiency-model.component.scss']
})
export class EfficiencyModelComponent implements OnInit, OnDestroy {
  readonly modelKeys = MODEL_KEYS;
  readonly modelLabels = MODEL_LABELS;
  readonly modelColors = MODEL_COLORS;

  options: EffOptions | null = null;
  optionsError: string | null = null;

  // data
  pcsIds = new Set<number>();
  dateFrom = '';
  dateTo = '';
  minLoadPct = 2;
  excludeSnapshots = true;
  groups = new Set<string>();
  // models
  gbParams: Record<string, any> = {};
  gamParams: Record<string, any> = {};
  booster: EffBooster = 'lightgbm';
  boostParams: Record<string, any> = {};
  splitMethod: 'chronological' | 'random' = 'chronological';
  testPct = 20;
  majorShare = 0.25;
  socTolerance = 5;
  runName = '';
  makeDefault = true;

  preview: EffPreview | null = null;
  previewing = false;
  training = false;
  trainError: string | null = null;

  runs: EffRun[] = [];
  runsLoading = true;
  run: EffRunDetail | null = null;
  runLoading = false;
  cycles: EffCycle[] = [];

  // result views
  curveUnit: number | null = null;
  curveDirection: EffDirection = 'discharge';
  scatterModel: EffModelKey = 'hybrid';
  pdTerm = '';
  cycleUnit: number | null = null;
  curveChart?: AnyConfig;
  scatterChart?: AnyConfig;
  shapChart?: AnyConfig;
  shapHeight = 260;
  pdChart?: AnyConfig;
  healthChart?: AnyConfig;
  boostChart?: AnyConfig;
  rteChart?: AnyConfig;
  compChart?: AnyConfig;

  private previewTimer?: ReturnType<typeof setTimeout>;

  constructor(private service: EfficiencyService, private route: ActivatedRoute, private router: Router) {}

  ngOnInit(): void {
    this.service.options().subscribe({
      next: (o) => {
        this.options = o;
        this.groups = new Set(o.feature_groups.map((g) => g.key));
        this.pcsIds = new Set(o.units.filter((u) => u.active > 0).map((u) => u.pcs_id));
        this.minLoadPct = o.defaults.min_load_frac * 100;
        this.testPct = o.defaults.test_fraction * 100;
        this.majorShare = o.defaults.major_share;
        this.socTolerance = o.defaults.soc_tolerance_pct;
        this.resetParams();
        this.schedulePreview();
        if (this.run) {
          this.buildCharts(); // feature labels come from the options
        }
      },
      error: (err) =>
        (this.optionsError = err?.status === 0 ? 'Could not reach the ML service. Is it running on port 8100?' : 'Could not load the options.')
    });
    this.loadRuns(Number(this.route.snapshot.queryParamMap.get('run')) || null);
  }

  ngOnDestroy(): void {
    clearTimeout(this.previewTimer);
  }

  // ---------------------------------------------------------------- inputs

  get gbSpecs(): EffParamSpec[] {
    return this.options?.models.greybox.params ?? [];
  }

  get gamSpecs(): EffParamSpec[] {
    return this.options?.models.gam.params ?? [];
  }

  get boostSpecs(): EffParamSpec[] {
    return this.options?.models.boosters.find((b) => b.key === this.booster)?.params ?? [];
  }

  resetParams(): void {
    const defaults = (specs: EffParamSpec[]) => Object.fromEntries(specs.map((p) => [p.name, p.default]));
    this.gbParams = defaults(this.gbSpecs);
    this.gamParams = defaults(this.gamSpecs);
    this.boostParams = defaults(this.boostSpecs);
  }

  setBooster(key: EffBooster): void {
    this.booster = key;
    this.boostParams = Object.fromEntries(this.boostSpecs.map((p) => [p.name, p.default]));
  }

  unitLabel(id: number): string {
    const u = this.options?.units.find((x) => x.pcs_id === id);
    return u ? `${u.site_name ?? u.system_name ?? ''} · ${u.pcs_code}` : `PCS ${id}`;
  }

  shortUnit(id: number | string): string {
    const u = this.options?.units.find((x) => x.pcs_id === Number(id));
    return u?.site_name?.replace(/ BESS Site| Grid Storage Site| Site/, '') ?? `PCS ${id}`;
  }

  toggleUnit(u: EffUnitCoverage): void {
    if (!u.active) {
      return;
    }
    this.pcsIds.has(u.pcs_id) ? this.pcsIds.delete(u.pcs_id) : this.pcsIds.add(u.pcs_id);
    this.pcsIds = new Set(this.pcsIds);
    this.schedulePreview();
  }

  toggleGroup(key: string, required: boolean): void {
    if (required) {
      return;
    }
    this.groups.has(key) ? this.groups.delete(key) : this.groups.add(key);
    this.groups = new Set(this.groups);
  }

  schedulePreview(): void {
    clearTimeout(this.previewTimer);
    this.previewTimer = setTimeout(() => this.loadPreview(), 450);
  }

  private selection() {
    return {
      pcs_ids: Array.from(this.pcsIds),
      date_from: this.dateFrom || null,
      date_to: this.dateTo || null,
      min_load_frac: Number(this.minLoadPct) / 100,
      exclude_snapshots: this.excludeSnapshots,
      feature_groups: Array.from(this.groups)
    };
  }

  private loadPreview(): void {
    if (!this.pcsIds.size) {
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
    if (!this.pcsIds.size) {
      return 'Choose at least one PCS unit';
    }
    if (this.preview && this.preview.rows < 200) {
      return `Only ${this.preview.rows} active readings (200 needed)`;
    }
    return null;
  }

  train(): void {
    if (this.problem || this.training) {
      return;
    }
    this.training = true;
    this.trainError = null;
    this.service
      .train({
        ...this.selection(),
        split_method: this.splitMethod,
        test_fraction: Number(this.testPct) / 100,
        random_state: 42,
        greybox_params: this.gbParams,
        gam_params: this.gamParams,
        booster: this.booster,
        booster_params: this.boostParams,
        major_share: Number(this.majorShare),
        soc_tolerance_pct: Number(this.socTolerance),
        run_name: this.runName.trim() || null,
        make_default: this.makeDefault
      })
      .subscribe({
        next: (run) => {
          this.training = false;
          this.loadRuns(run.run_id);
        },
        error: (err) => {
          const d = err?.error?.detail;
          this.trainError = typeof d === 'string' ? d : d?.message || 'Training failed.';
          this.training = false;
          this.loadRuns();
        }
      });
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
        const units = Object.keys(run.results?.curves ?? {}).map(Number);
        if (!this.curveUnit || !units.includes(this.curveUnit)) {
          this.curveUnit = units.includes(6) ? 6 : units[0] ?? null;
        }
        if (!this.cycleUnit || !run.pcs_ids.includes(this.cycleUnit)) {
          this.cycleUnit = this.curveUnit;
        }
        this.pdTerm = Object.keys(run.results?.gam.partial_dependence ?? {})[0] ?? '';
        this.buildCharts();
        if (run.status === 'COMPLETED') {
          this.service.cycles(id).subscribe((c) => {
            this.cycles = c;
            this.buildCycleCharts();
          });
        } else {
          this.cycles = [];
          this.buildCycleCharts();
        }
      },
      error: () => (this.runLoading = false)
    });
  }

  makeDefaultRun(r: EffRun, event?: Event): void {
    event?.stopPropagation();
    this.service.makeDefault(r.run_id).subscribe(() => this.loadRuns(this.run?.run_id ?? null));
  }

  deleteRun(r: EffRun, event: Event): void {
    event.stopPropagation();
    if (!window.confirm(`Delete efficiency run #${r.run_id}, its scores and cycles?`)) {
      return;
    }
    this.service.deleteRun(r.run_id).subscribe(() => {
      if (this.run?.run_id === r.run_id) {
        this.run = null;
      }
      this.loadRuns();
    });
  }

  reuse(r: EffRunDetail): void {
    this.pcsIds = new Set(r.pcs_ids);
    this.dateFrom = r.date_from ?? '';
    this.dateTo = r.date_to ?? '';
    this.minLoadPct = r.min_load_frac * 100;
    this.groups = new Set(r.feature_groups);
    this.splitMethod = r.split_method as 'chronological' | 'random';
    this.testPct = r.test_fraction * 100;
    this.booster = r.booster;
    this.gbParams = { ...r.params['greybox'] };
    this.gamParams = { ...r.params['gam'] };
    this.boostParams = { ...r.params[r.booster] };
    this.majorShare = r.params['major_share'] ?? this.majorShare;
    this.socTolerance = r.params['soc_tolerance_pct'] ?? this.socTolerance;
    this.excludeSnapshots = r.params['exclude_snapshots'] ?? true;
    this.runName = '';
    this.schedulePreview();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  // ---------------------------------------------------------------- formatting

  fmtPct = fmtPct;
  fmtNum = fmtNum;

  score(s: EffScores | undefined, key: keyof EffScores, digits = 3): string {
    const v = s?.[key];
    return typeof v === 'number' && Number.isFinite(v) ? v.toFixed(digits) : '—';
  }

  best(key: keyof EffScores): EffModelKey | null {
    const m = this.run?.metrics;
    if (!m) {
      return null;
    }
    const higher = key === 'r2';
    return MODEL_KEYS.reduce<EffModelKey | null>((b, k) => {
      const v = m[k].test[key] as number | null;
      if (v === null || v === undefined) {
        return b;
      }
      if (b === null) {
        return k;
      }
      const bv = m[b].test[key] as number;
      const better = key === 'bias_pp' ? Math.abs(v) < Math.abs(bv) : higher ? v > bv : v < bv;
      return better ? k : b;
    }, null);
  }

  get unitKeys(): string[] {
    return Object.keys(this.run?.results?.metrics_detail.by_unit ?? {});
  }

  get bandKeys(): string[] {
    return Object.keys(this.run?.results?.metrics_detail.by_load_band ?? {});
  }

  get dirKeys(): string[] {
    return Object.keys(this.run?.results?.metrics_detail.by_direction ?? {});
  }

  get gbDirections(): string[] {
    return Object.keys(this.run?.results?.greybox.directions ?? {});
  }

  dirLabel(d: string): string {
    return d === 'chg' ? 'Charge' : d === 'dis' ? 'Discharge' : 'Both';
  }

  healthUnits(): string[] {
    return Object.keys(this.run?.results?.health.per_unit ?? {});
  }

  pdKeys(): string[] {
    return Object.keys(this.run?.results?.gam.partial_dependence ?? {});
  }

  featureLabel(f: string): string {
    if (f.startsWith('load_frac|')) {
      return `Load fraction · ${f.endsWith('|charge') ? 'charge' : 'discharge'}`;
    }
    if (f === 'pcs_id') {
      return 'PCS unit';
    }
    for (const g of this.options?.feature_groups ?? []) {
      const s = g.features.find((x) => x.key === f);
      if (s) {
        return s.label + (s.unit ? ` (${s.unit})` : '');
      }
    }
    return f;
  }

  groupLabels(r: EffRun): string {
    return r.feature_groups.map((g) => this.options?.feature_groups.find((x) => x.key === g)?.label ?? g).join(' · ');
  }

  window(r: EffRun): string {
    return `${r.date_from ?? 'start'} → ${r.date_to ?? 'end'}`;
  }

  duration(ms: number | null): string {
    return ms === null ? '' : ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
  }

  plantTime(ts: string | null | undefined): string {
    return ts ? ts.replace('T', ' ').slice(0, 16) : '—';
  }

  paramSummary(p: Record<string, unknown> | undefined): string {
    return Object.entries(p ?? {})
      .map(([k, v]) => `${k}=${v}`)
      .join(' · ');
  }

  get cycleRows(): EffCycle[] {
    return this.cycles.filter((c) => c.pcs_id === this.cycleUnit);
  }

  get closedShare(): string {
    const all = this.cycles.length;
    return all ? `${this.cycles.filter((c) => c.closed).length} / ${all}` : '—';
  }

  // ---------------------------------------------------------------- charts

  buildCharts(): void {
    this.buildCurve();
    this.buildScatter();
    this.buildShap();
    this.buildPd();
    this.buildHealth();
    this.buildBoost();
  }

  buildCurve(): void {
    const res = this.run?.results;
    const curves = res && this.curveUnit ? res.curves[String(this.curveUnit)] : null;
    if (!curves) {
      this.curveChart = undefined;
      return;
    }
    const charge = this.curveDirection === 'charge';
    const measured = (this.run?.predictions ?? [])
      .filter((p) => p.pcs_id === this.curveUnit && p.charge === charge)
      .map((p) => ({ x: p.load_frac, y: p.actual, test: p.set === 'test' }));
    this.curveChart = curveChart(curves, this.curveDirection, measured);
  }

  buildScatter(): void {
    const preds = (this.run?.predictions ?? []).filter((p) => p.set === 'test');
    if (!preds.length) {
      this.scatterChart = undefined;
      return;
    }
    const k = this.scatterModel;
    const vals = preds.flatMap((p) => [p.actual, p[k]]);
    const lo = Math.floor(Math.min(...vals) * 2) / 2;
    const hi = Math.min(100, Math.ceil(Math.max(...vals) * 2) / 2);
    this.scatterChart = {
      type: 'scatter',
      data: {
        datasets: [
          {
            label: 'Perfect prediction',
            type: 'line',
            data: [
              { x: lo, y: lo },
              { x: hi, y: hi }
            ],
            borderColor: 'rgba(71, 85, 105, 0.5)',
            borderDash: [4, 4],
            borderWidth: 1.5,
            pointRadius: 0
          } as any,
          {
            label: `${MODEL_LABELS[k]} · charge`,
            data: preds.filter((p) => p.charge).map((p) => ({ x: p.actual, y: p[k] })),
            backgroundColor: MODEL_COLORS[k],
            pointRadius: 2.5,
            pointStyle: 'triangle'
          },
          {
            label: `${MODEL_LABELS[k]} · discharge`,
            data: preds.filter((p) => !p.charge).map((p) => ({ x: p.actual, y: p[k] })),
            backgroundColor: MODEL_COLORS[k],
            pointRadius: 2.5,
            pointStyle: 'circle'
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        plugins: {
          legend: legend(),
          tooltip: {
            ...tooltip,
            callbacks: {
              label: (ctx: TooltipItem<'scatter'>) =>
                `measured ${(ctx.parsed.x as number).toFixed(2)} % · predicted ${(ctx.parsed.y as number).toFixed(2)} %`
            }
          }
        },
        scales: { x: axis('Measured η (%)', { min: lo, max: hi }), y: axis('Predicted η (%)', { min: lo, max: hi }) }
      }
    } as AnyConfig;
  }

  buildShap(): void {
    const shap = this.run?.results?.shap;
    if (!shap) {
      this.shapChart = undefined;
      return;
    }
    const entries = Object.entries(shap.mean_abs_pp).sort((a, b) => b[1] - a[1]);
    this.shapHeight = Math.max(160, entries.length * 24 + 40);
    this.shapChart = hbar(
      entries.map(([f]) => this.featureLabel(f)),
      entries.map(([, v]) => v),
      MODEL_COLORS.hybrid,
      (v) => `${v.toFixed(3)} pp`,
      'Mean |SHAP| on the residual (η percentage points)'
    );
  }

  buildPd(): void {
    const pd = this.run?.results?.gam.partial_dependence;
    const curve = pd?.[this.pdTerm];
    if (!curve) {
      this.pdChart = undefined;
      return;
    }
    this.pdChart = {
      type: 'line',
      data: {
        datasets: [
          {
            label: 'GAM',
            data: curve.map((p) => ({ x: p.x, y: p.y })),
            borderColor: MODEL_COLORS.gam,
            backgroundColor: MODEL_COLORS.gam,
            borderWidth: 2,
            pointRadius: 0,
            tension: 0.3
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        interaction: { mode: 'nearest', intersect: false },
        plugins: {
          legend: legend(false),
          tooltip: {
            ...tooltip,
            callbacks: { label: (ctx: TooltipItem<'line'>) => `${(ctx.parsed.y as number) >= 0 ? '+' : ''}${(ctx.parsed.y as number).toFixed(3)} pp` }
          }
        },
        scales: {
          x: { ...axis(this.featureLabel(this.pdTerm)), type: 'linear' },
          y: axis('Effect on η (pp, centred)')
        }
      }
    } as AnyConfig;
  }

  buildHealth(): void {
    const rows = this.run?.results?.health.loss_index ?? [];
    if (!rows.length) {
      this.healthChart = undefined;
      return;
    }
    const units = Array.from(new Set(rows.map((r) => r.pcs_id)));
    const weeks = Array.from(new Set(rows.map((r) => r.week))).sort();
    this.healthChart = {
      type: 'line',
      data: {
        labels: weeks,
        datasets: units.map((u, i) => ({
          label: this.shortUnit(u),
          data: weeks.map((w) => rows.find((r) => r.pcs_id === u && r.week === w)?.index ?? null),
          borderColor: SERIES[i % SERIES.length],
          backgroundColor: SERIES[i % SERIES.length],
          borderWidth: 2,
          pointRadius: 3,
          spanGaps: false
        }))
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: legend(),
          tooltip: { ...tooltip, callbacks: { label: (ctx: TooltipItem<'line'>) => `${ctx.dataset.label}: ${(ctx.parsed.y as number).toFixed(3)}` } }
        },
        scales: { x: axis('Week starting'), y: axis('Loss index (measured / modelled)') }
      }
    } as AnyConfig;
  }

  buildBoost(): void {
    const c = this.run?.results?.boost_curve ?? [];
    if (!c.length) {
      this.boostChart = undefined;
      return;
    }
    this.boostChart = {
      type: 'line',
      data: {
        labels: c.map((p) => p.iteration),
        datasets: [
          { label: 'Training rows', data: c.map((p) => p.train_rmse), borderColor: '#2a78d6', borderWidth: 2, pointRadius: 0 },
          { label: 'Test rows', data: c.map((p) => p.valid_rmse), borderColor: '#d9480f', borderWidth: 2, pointRadius: 0 }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        interaction: { mode: 'index', intersect: false },
        plugins: { legend: legend(), tooltip },
        scales: { x: axis('Boosting round', { ticks: { maxTicksLimit: 10, color: INK } }), y: axis('Residual RMSE (pp)') }
      }
    } as AnyConfig;
  }

  buildCycleCharts(): void {
    const rows = this.cycleRows;
    if (!rows.length) {
      this.rteChart = undefined;
      this.compChart = undefined;
      return;
    }
    const labels = rows.map((c) => c.start_ts.slice(5, 10));
    const line = (label: string, data: (number | null)[], color: string, dash: number[] = []) => ({
      label,
      data,
      borderColor: color,
      backgroundColor: color,
      borderWidth: 2,
      borderDash: dash,
      pointRadius: rows.map((c) => (c.closed ? 3 : 5)),
      pointStyle: rows.map((c) => (c.closed ? 'circle' : 'crossRot')),
      spanGaps: true
    });
    this.rteChart = {
      type: 'line',
      data: {
        labels,
        datasets: [
          line('DC (battery terminals)', rows.map((c) => c.rte_dc_pct), RTE_COLORS.dc),
          line('AC (PCS terminals)', rows.map((c) => c.rte_ac_pct), RTE_COLORS.ac),
          line('System (POI, with auxiliaries)', rows.map((c) => c.rte_sys_pct), RTE_COLORS.sys)
        ]
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
            callbacks: { label: (ctx: TooltipItem<'line'>) => `${ctx.dataset.label}: ${(ctx.parsed.y as number)?.toFixed(2)} %` }
          }
        },
        scales: { x: axis('Cycle start'), y: axis('Round-trip efficiency (%)') }
      }
    } as AnyConfig;
    this.compChart = {
      type: 'line',
      data: {
        labels,
        datasets: [
          line('AC measured', rows.map((c) => c.rte_ac_pct), RTE_COLORS.ac),
          line('AC composed (DC × PCS model)', rows.map((c) => c.rte_ac_comp_pct), RTE_COLORS.ac, [5, 4]),
          line('System measured', rows.map((c) => c.rte_sys_pct), RTE_COLORS.sys),
          line('System composed', rows.map((c) => c.rte_sys_comp_pct), RTE_COLORS.sys, [5, 4])
        ]
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
            callbacks: { label: (ctx: TooltipItem<'line'>) => `${ctx.dataset.label}: ${(ctx.parsed.y as number)?.toFixed(2)} %` }
          }
        },
        scales: { x: axis('Cycle start'), y: axis('Round-trip efficiency (%)') }
      }
    } as AnyConfig;
  }

  dcCoefs(): { key: string; label: string; std: number; raw: number }[] {
    const m = this.run?.results?.rte.dc_model;
    if (!m) {
      return [];
    }
    return m.features
      .map((f) => ({ key: f, label: m.labels[f] ?? f, std: m.coef_std[f], raw: m.coef_raw[f] }))
      .sort((a, b) => Math.abs(b.std) - Math.abs(a.std));
  }
}
