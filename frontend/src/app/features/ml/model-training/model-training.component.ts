import { CommonModule } from '@angular/common';
import { Component, OnDestroy, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { ChartConfiguration, TooltipItem } from 'chart.js';

import {
  MlDataSelection,
  MlGrain,
  MlImportanceMethod,
  MlMetricKey,
  MlModelType,
  MlParamSpec,
  MlPreview,
  MlRun,
  MlRunDetail,
  MlScope,
  MlSplit,
  MlSystemCoverage,
  MlSystemScores,
  MlTrainOptions,
  MlTrainingMode
} from '../../../core/models/ml-training.model';
import { SohMlService } from '../../../core/services/soh-ml.service';
import { ChartCanvasComponent } from '../../telemetry/graphs/chart-canvas.component';
import { timeAxis } from '../../telemetry/graphs/time-axis';

type AnyConfig = ChartConfiguration;

/* Chart colours (checked with the dataviz palette validator): the two models; training vs test rows. */
const MODEL_COLORS: Record<MlModelType, string> = { xgboost: '#6d5bd0', lightgbm: '#2aa198' };
const TRAIN = '#2a78d6';
const TEST = '#eb6834';
const INK = '#475569';
// feature selection: kept features in ink, dropped ones recessive
const KEPT = '#475569';
const DROPPED = '#cdd2d9';
const INK_MUTED = '#6b6f76';
const GRID = 'rgba(0, 0, 0, 0.06)';

function tooltipBase() {
  return { backgroundColor: '#26282b', padding: 10, boxPadding: 4, cornerRadius: 6, titleFont: { weight: 'bold' as const } };
}

function axis(title?: string, extra: Record<string, unknown> = {}) {
  return {
    ticks: { color: INK_MUTED, font: { size: 11 } },
    grid: { color: GRID },
    border: { display: false },
    title: { display: !!title, text: title ?? '', color: INK_MUTED, font: { size: 11 } },
    ...extra
  };
}

function legend(show = true) {
  return {
    display: show,
    position: 'top' as const,
    align: 'end' as const,
    labels: { usePointStyle: true, pointStyle: 'rectRounded', boxWidth: 10, boxHeight: 10, color: '#52565c', font: { size: 12 } }
  };
}

/** Plant-local ISO time without a zone -> ms, read as a local clock time. */
const ms = (iso: string) => new Date(iso.slice(0, 19)).getTime();

@Component({
  selector: 'app-model-training',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink, ChartCanvasComponent],
  templateUrl: './model-training.component.html',
  styleUrl: './model-training.component.scss'
})
export class ModelTrainingComponent implements OnInit, OnDestroy {
  options: MlTrainOptions | null = null;
  optionsError: string | null = null;

  // ---- scope: a base model (plant-agnostic) or a battery system (plant) model
  scope: MlScope = 'base';
  /** Base models: the battery systems trained on. */
  baseSystems = new Set<number>();
  /** Base models: a battery system left out of training and scored separately. */
  holdoutId: number | null = null;
  /** Battery system models: the plant. */
  siteId: number | null = null;
  systemId: number | null = null;
  trainingMode: MlTrainingMode = 'finetune';
  parentRunId: number | null = null;

  // ---- form
  modelType: MlModelType = 'xgboost';
  params: Record<string, number | boolean> = {};
  runName = '';
  grain: MlGrain = 'hour';
  dateFrom = '';
  dateTo = '';
  groups = new Set<string>();
  moduleRowsOnly = true;
  includeSnapshots = false;
  splitMethod: MlSplit = 'chronological';
  testPercent = 20;
  seed = 42;
  // feature selection: keep features with at least this share of the importance (0 = keep all)
  minImportancePct = 1;
  importanceMethod: MlImportanceMethod = 'auto';

  preview: MlPreview | null = null;
  previewLoading = false;
  private previewTimer?: ReturnType<typeof setTimeout>;
  private previewSeq = 0;

  training = false;
  trainError: string | null = null;

  // ---- selected run
  run: MlRunDetail | null = null;
  runLoading = false;
  curveMetric: 'rmse' | 'mae' = 'rmse';
  curveChart?: AnyConfig;
  predictionChart?: AnyConfig;
  importanceChart?: AnyConfig;
  importanceHeight = 240;
  selectionChart?: AnyConfig;
  selectionHeight = 240;

  // ---- history + comparison
  runs: MlRun[] = [];
  runsLoading = true;
  runsError: string | null = null;
  historyFilter: MlModelType | '' = '';
  /** '' = all runs, 'base' = base runs, or a battery system id. */
  scopeFilter: '' | 'base' | number = '';
  compareIds = new Set<number>();
  compareMetric: MlMetricKey = 'rmse';
  compareChart?: AnyConfig;
  confirmDeleteId: number | null = null;
  activating = false;

  constructor(private service: SohMlService) {}

  ngOnInit(): void {
    this.service.trainOptions().subscribe({
      next: (options) => {
        this.options = options;
        this.baseSystems = new Set(options.systems.filter((x) => x.has_telemetry).map((x) => x.battery_system_id));
        const first = options.systems.find((x) => x.has_telemetry);
        this.siteId = first?.site_id ?? null;
        this.systemId = first?.battery_system_id ?? null;
        this.groups = new Set(this.allowedGroups.map((g) => g.key));
        this.dateFrom = options.coverage.bms_from;
        // default: up to the day before the first snapshot-loaded (simulated) day
        this.dateTo = options.coverage.bms_to;
        this.minImportancePct = options.feature_selection.default_min_importance_pct;
        this.resetParams();
        this.schedulePreview();
      },
      error: () => (this.optionsError = 'Could not reach the SOH model service. Is it running on port 8100?')
    });
    this.loadRuns(true);
  }

  ngOnDestroy(): void {
    clearTimeout(this.previewTimer);
  }

  // ---------------------------------------------------------------- scope

  get systems(): MlSystemCoverage[] {
    return this.options?.systems ?? [];
  }

  get sites(): { site_id: number; site_name: string }[] {
    const seen = new Map<number, string>();
    this.systems.forEach((x) => seen.set(x.site_id, x.site_name));
    return Array.from(seen, ([site_id, site_name]) => ({ site_id, site_name }));
  }

  get siteSystems(): MlSystemCoverage[] {
    return this.systems.filter((x) => x.site_id === this.siteId);
  }

  get system(): MlSystemCoverage | undefined {
    return this.systems.find((x) => x.battery_system_id === this.systemId);
  }

  systemName(id: number | null | undefined): string {
    const x = this.systems.find((y) => y.battery_system_id === id);
    return x ? `${x.site_name} · ${x.system_name}` : id === null || id === undefined ? '' : `system ${id}`;
  }

  shortSystem(id: number | string | null | undefined): string {
    return this.systems.find((y) => y.battery_system_id === Number(id))?.system_name ?? `system ${id}`;
  }

  /** "base" or "Site · system" for a run. */
  scopeLabel(run: MlRun): string {
    return run.scope === 'system' ? this.systemName(run.battery_system_id) : 'Base';
  }

  setScope(scope: MlScope): void {
    if (this.scope === scope) {
      return;
    }
    this.scope = scope;
    // raw kWh are plant-size dependent: base models use throughput / rated kWh instead
    const allowed = new Set(this.allowedGroups.map((g) => g.key));
    const next = new Set([...this.groups].filter((g) => allowed.has(g)));
    if (scope === 'base' && this.groups.has('throughput')) {
      next.add('throughput_norm');
    }
    this.groups = next;
    if (scope === 'system' && this.trainingMode === 'finetune') {
      this.applyParent();
    }
    this.schedulePreview();
  }

  onSiteChange(): void {
    const list = this.siteSystems;
    this.systemId = (list.find((x) => x.has_telemetry) ?? list[0])?.battery_system_id ?? null;
    this.schedulePreview();
  }

  toggleBaseSystem(id: number): void {
    if (this.baseSystems.has(id)) {
      this.baseSystems.delete(id);
      if (this.holdoutId === id) {
        this.holdoutId = null;
      }
    } else {
      this.baseSystems.add(id);
    }
    this.baseSystems = new Set(this.baseSystems);
    this.schedulePreview();
  }

  /** Completed base runs a battery system model can be fine-tuned from (newest first). */
  get baseRuns(): MlRun[] {
    return this.runs.filter((r) => r.scope === 'base' && r.status === 'COMPLETED');
  }

  get parentRun(): MlRun | undefined {
    return this.runs.find((r) => r.run_id === this.parentRunId);
  }

  /** Fine-tuning a base run: its algorithm, grain and feature groups are used (and its features). */
  get finetuning(): boolean {
    return this.scope === 'system' && this.trainingMode === 'finetune';
  }

  setTrainingMode(mode: MlTrainingMode): void {
    this.trainingMode = mode;
    if (mode === 'finetune') {
      this.applyParent();
    }
    this.schedulePreview();
  }

  applyParent(): void {
    if (this.parentRunId === null || !this.baseRuns.some((r) => r.run_id === this.parentRunId)) {
      const preferred = this.baseRuns.find((r) => r.is_active) ?? this.baseRuns[0];
      this.parentRunId = preferred?.run_id ?? null;
    }
    const parent = this.parentRun;
    if (!parent) {
      return;
    }
    if (this.modelType !== parent.model_type) {
      this.modelType = parent.model_type;
      this.resetParams();
    }
    this.grain = parent.grain;
    this.groups = new Set(parent.feature_groups);
    this.moduleRowsOnly = parent.module_rows_only;
    this.schedulePreview();
  }

  get allowedGroups() {
    return (this.options?.feature_groups ?? []).filter((g) => (g.scopes ?? ['base', 'system']).includes(this.scope));
  }

  // ---------------------------------------------------------------- form

  get paramSpecs(): MlParamSpec[] {
    return this.options?.models.find((m) => m.key === this.modelType)?.params ?? [];
  }

  modelLabel(key: string): string {
    return this.options?.models.find((m) => m.key === key)?.label ?? key;
  }

  setModel(model: MlModelType): void {
    this.modelType = model;
    this.resetParams();
  }

  resetParams(): void {
    this.params = Object.fromEntries(this.paramSpecs.map((p) => [p.name, p.default]));
  }

  toggleGroup(key: string): void {
    if (this.groups.has(key)) {
      this.groups.delete(key);
    } else {
      this.groups.add(key);
    }
    this.groups = new Set(this.groups);
    this.schedulePreview();
  }

  private get selection(): MlDataSelection {
    const base = this.scope === 'base';
    return {
      grain: this.grain,
      date_from: this.dateFrom || null,
      date_to: this.dateTo || null,
      feature_groups: [...this.groups],
      module_rows_only: this.moduleRowsOnly,
      include_snapshots: this.includeSnapshots,
      scope: this.scope,
      battery_system_id: base ? null : this.systemId,
      systems: base ? [...this.baseSystems] : null,
      holdout_system_id: base ? this.holdoutId : null
    };
  }

  /** Refresh the row count / SOH spread shortly after the data selection changes. */
  schedulePreview(): void {
    clearTimeout(this.previewTimer);
    this.previewTimer = setTimeout(() => {
      const seq = ++this.previewSeq;
      this.previewLoading = true;
      this.service.preview(this.selection).subscribe({
        next: (p) => {
          if (seq === this.previewSeq) {
            this.preview = p;
            this.previewLoading = false;
          }
        },
        error: () => {
          if (seq === this.previewSeq) {
            this.preview = null;
            this.previewLoading = false;
          }
        }
      });
    }, 350);
  }

  get testRows(): number {
    return this.preview?.rows ? Math.max(1, Math.round(this.preview.rows * this.testPercent / 100)) : 0;
  }

  get problem(): string | null {
    if (this.scope === 'system') {
      if (!this.system) {
        return 'Choose the site and battery system.';
      }
      if (!this.system.has_telemetry) {
        return `${this.system.system_name} has no BMS telemetry to train on.`;
      }
      if (this.finetuning && !this.parentRun) {
        return 'Choose the base run to fine-tune (train a base model first), or train from scratch.';
      }
    } else {
      const training = [...this.baseSystems].filter((id) => id !== this.holdoutId);
      if (!training.length) {
        return 'Choose at least one battery system to train the base model on.';
      }
    }
    if (!this.groups.size) {
      return 'Choose at least one feature group.';
    }
    if (this.preview && this.preview.rows < 10) {
      return `Only ${this.preview.rows} rows match the data selection; at least 10 are needed.`;
    }
    if (this.testPercent < 5 || this.testPercent > 50) {
      return 'The test share must be between 5 and 50 %.';
    }
    if (this.minImportancePct === null || this.minImportancePct < 0 || this.minImportancePct >= 100) {
      return 'The importance threshold must be between 0 and 100 %.';
    }
    return null;
  }

  get lowVariance(): boolean {
    return !!this.preview?.rows && (this.preview.target_std ?? 0) < 0.01;
  }

  train(): void {
    if (this.problem || this.training) {
      return;
    }
    this.training = true;
    this.trainError = null;
    this.service
      .train({
        ...this.selection,
        model_type: this.modelType,
        params: this.params,
        run_name: this.runName.trim() || null,
        split_method: this.splitMethod,
        test_fraction: this.testPercent / 100,
        random_state: Number(this.seed) || 0,
        min_importance_pct: this.finetuning ? 0 : Number(this.minImportancePct) || 0,
        importance_method: this.importanceMethod,
        training_mode: this.scope === 'system' ? this.trainingMode : 'scratch',
        parent_run_id: this.finetuning ? this.parentRunId : null
      })
      .subscribe({
        next: (run) => {
          this.training = false;
          this.showRun(run);
          this.loadRuns();
        },
        error: (err) => {
          this.training = false;
          const detail = err?.error?.detail;
          this.trainError = typeof detail === 'string' ? detail : detail?.message || 'Training failed. Is the model service running?';
          this.loadRuns();
        }
      });
  }

  /** Copy a run's settings into the form (to train a variant). */
  reuse(run: MlRun): void {
    this.scope = run.scope ?? 'base';
    if (run.scope === 'system') {
      const x = this.systems.find((y) => y.battery_system_id === run.battery_system_id);
      this.siteId = x?.site_id ?? this.siteId;
      this.systemId = run.battery_system_id;
      this.trainingMode = run.training_mode ?? 'scratch';
      this.parentRunId = run.parent_run_id;
    } else {
      this.baseSystems = new Set(
        [...(run.systems ?? this.systems.filter((y) => y.has_telemetry).map((y) => y.battery_system_id)),
         ...(run.holdout_system_id ? [run.holdout_system_id] : [])]
      );
      this.holdoutId = run.holdout_system_id;
    }
    this.modelType = run.model_type;
    this.params = { ...Object.fromEntries(this.paramSpecs.map((p) => [p.name, p.default])), ...run.params };
    this.grain = run.grain;
    this.dateFrom = run.date_from ?? '';
    this.dateTo = run.date_to ?? '';
    this.groups = new Set(run.feature_groups);
    this.moduleRowsOnly = run.module_rows_only;
    this.includeSnapshots = run.include_snapshots;
    this.splitMethod = run.split_method;
    this.testPercent = Math.round(run.test_fraction * 100);
    this.seed = run.random_state;
    this.minImportancePct = run.min_importance_pct;
    this.importanceMethod = run.min_importance_pct > 0 ? (run.importance_method ?? 'auto') : 'auto';
    this.runName = run.run_name ? `${run.run_name} (copy)` : '';
    this.schedulePreview();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  // ---------------------------------------------------------------- one run

  open(run: MlRun): void {
    this.runLoading = true;
    this.service.run(run.run_id).subscribe({
      next: (detail) => {
        this.runLoading = false;
        this.showRun(detail);
      },
      error: () => (this.runLoading = false)
    });
  }

  private showRun(run: MlRunDetail): void {
    this.run = run;
    this.buildCurve();
    this.buildPredictions();
    this.buildImportance();
    this.buildSelection();
    setTimeout(() => document.getElementById('run-result')?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 50);
  }

  setCurveMetric(metric: 'rmse' | 'mae'): void {
    this.curveMetric = metric;
    this.buildCurve();
  }

  private buildCurve(): void {
    const curve = this.run?.curve ?? [];
    if (!curve.length) {
      this.curveChart = undefined;
      return;
    }
    const key = this.curveMetric;
    const line = (label: string, data: number[], color: string) => ({
      label, data, borderColor: color, backgroundColor: color, borderWidth: 2, pointRadius: 0, pointHoverRadius: 4, tension: 0.2
    });
    this.curveChart = {
      type: 'line',
      data: {
        labels: curve.map((c) => c.iteration),
        datasets: [
          line('Training rows', curve.map((c) => (key === 'rmse' ? c.train_rmse : c.train_mae)), TRAIN),
          line('Test rows', curve.map((c) => (key === 'rmse' ? c.valid_rmse : c.valid_mae)), TEST)
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        scales: {
          x: axis('Boosting round', { grid: { display: false }, ticks: { color: INK_MUTED, font: { size: 11 }, maxTicksLimit: 10 } }),
          y: axis(`${key.toUpperCase()} (SOH % points)`, { type: 'logarithmic' })
        },
        plugins: {
          legend: legend(),
          tooltip: {
            ...tooltipBase(),
            callbacks: {
              title: (items: TooltipItem<'line'>[]) => `Round ${items[0]?.label}`,
              label: (item: TooltipItem<'line'>) => ` ${item.dataset.label}: ${Number(item.raw).toFixed(5)}`
            }
          }
        }
      }
    } as AnyConfig;
  }

  private buildPredictions(): void {
    const rows = this.run?.predictions ?? [];
    if (!rows.length) {
      this.predictionChart = undefined;
      return;
    }
    const xs = rows.map((r) => ms(r.ts));
    const xMin = Math.min(...xs);
    const xMax = Math.max(...xs);
    const time = timeAxis(xMin, xMax === xMin ? xMin + 3_600_000 : xMax);
    const points = (set: 'train' | 'test') => rows.filter((r) => r.set === set).map((r) => ({ x: ms(r.ts), y: r.predicted }));
    this.predictionChart = {
      type: 'line',
      data: {
        datasets: [
          { label: 'Actual SOH', data: rows.map((r) => ({ x: ms(r.ts), y: r.actual })), borderColor: INK, backgroundColor: INK,
            borderWidth: 2, pointRadius: 0, pointHoverRadius: 3, order: 3 },
          { label: 'Predicted · training rows', data: points('train'), type: 'scatter', backgroundColor: TRAIN, borderColor: '#fff',
            borderWidth: 1, pointRadius: 3, pointHoverRadius: 5, order: 2 },
          { label: 'Predicted · test rows', data: points('test'), type: 'scatter', backgroundColor: TEST, borderColor: '#fff',
            borderWidth: 1, pointRadius: 4, pointHoverRadius: 6, order: 1 }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        parsing: false,
        interaction: { mode: 'nearest', axis: 'x', intersect: false },
        scales: {
          x: { ...time, ticks: { ...time.ticks, color: INK_MUTED, font: { size: 11 } } },
          y: axis('SOH (%)', { grace: '5%' })
        },
        plugins: {
          legend: legend(),
          tooltip: {
            ...tooltipBase(),
            callbacks: {
              title: (items: TooltipItem<'line'>[]) => new Date(Number((items[0]?.raw as { x: number })?.x)).toLocaleString(),
              label: (item: TooltipItem<'line'>) => ` ${item.dataset.label}: ${Number((item.raw as { y: number }).y).toFixed(4)} %`
            }
          }
        }
      }
    } as AnyConfig;
  }

  private buildImportance(): void {
    // features that contributed at least 0.1 % of the gain (linear trees put nearly all of it in a few)
    const entries = Object.entries(this.run?.feature_importance ?? {}).filter(([, v]) => v >= 0.001).slice(0, 15);
    if (!entries.length) {
      this.importanceChart = undefined;
      return;
    }
    this.importanceHeight = Math.max(160, entries.length * 24 + 40);
    const label = (key: string) =>
      this.options?.feature_groups.flatMap((g) => g.features).find((f) => f.key === key)?.label ?? key;
    this.importanceChart = {
      type: 'bar',
      data: {
        labels: entries.map(([k]) => label(k)),
        datasets: [{ label: 'Share of gain', data: entries.map(([, v]) => v * 100), backgroundColor: INK, borderRadius: 4,
                     borderSkipped: 'start', maxBarThickness: 16 }]
      },
      options: {
        indexAxis: 'y',
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: axis('Share of the total gain (%)', { beginAtZero: true, grace: '18%' }),
          y: axis(undefined, { grid: { display: false }, ticks: { color: INK_MUTED, font: { size: 11 }, autoSkip: false } })
        },
        plugins: {
          legend: legend(false),
          valueLabels: { format: (v: number) => `${v.toFixed(1)}%` },
          tooltip: { ...tooltipBase(), callbacks: { label: (item: TooltipItem<'bar'>) => ` ${Number(item.raw).toFixed(2)}% of the gain` } }
        }
      }
    } as AnyConfig;
  }

  /** Screening importance of every candidate feature: the kept ones against the dropped ones. */
  private buildSelection(): void {
    const run = this.run;
    const shares = run?.selection_importance;
    if (!run || !shares || !Object.keys(shares).length) {
      this.selectionChart = undefined;
      return;
    }
    const kept = new Set(run.features);
    const entries = Object.entries(shares).sort((a, b) => b[1] - a[1]);
    this.selectionHeight = Math.max(180, entries.length * 20 + 40);
    const threshold = run.min_importance_pct;
    this.selectionChart = {
      type: 'bar',
      data: {
        labels: entries.map(([k]) => this.featureLabel(k)),
        datasets: [{
          label: 'Screening importance',
          data: entries.map(([, v]) => v * 100),
          backgroundColor: entries.map(([k]) => (kept.has(k) ? KEPT : DROPPED)),
          borderRadius: 3,
          borderSkipped: 'start',
          maxBarThickness: 14
        }]
      },
      options: {
        indexAxis: 'y',
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: axis(`Share of the ${run.importance_method ?? ''} importance (%)`, { beginAtZero: true, grace: '15%' }),
          y: axis(undefined, { grid: { display: false }, ticks: { color: INK_MUTED, font: { size: 11 }, autoSkip: false } })
        },
        plugins: {
          legend: legend(false),
          valueLabels: { format: (v: number) => `${v.toFixed(1)}%` },
          tooltip: {
            ...tooltipBase(),
            callbacks: {
              label: (item: TooltipItem<'bar'>) => {
                const key = entries[item.dataIndex][0];
                return ` ${Number(item.raw).toFixed(2)}% · ${kept.has(key) ? 'kept' : `dropped (below ${threshold}%)`}`;
              }
            }
          }
        }
      }
    } as AnyConfig;
  }

  featureLabel(key: string): string {
    return this.options?.feature_groups.flatMap((g) => g.features).find((f) => f.key === key)?.label ?? key;
  }

  /** "4 of 24" for a run that dropped features, else the count. */
  featureCount(run: MlRun): string {
    const candidates = run.candidate_features?.length ?? run.features.length;
    return candidates > run.features.length ? `${run.features.length} of ${candidates}` : `${run.features.length}`;
  }

  get candidateCount(): number {
    return (this.options?.feature_groups ?? []).filter((g) => this.groups.has(g.key)).reduce((n, g) => n + g.features.length, 0);
  }

  get methodHelp(): string {
    return this.options?.feature_selection.methods.find((m) => m.key === this.importanceMethod)?.help ?? '';
  }

  /** Make a run the default of its scope; with remove, take the run's scope default away. */
  useForPredictions(run: MlRun, remove = false): void {
    this.activating = true;
    this.service.activate(remove ? null : run.run_id, run.scope === 'system' ? run.battery_system_id : null).subscribe({
      next: () => {
        this.activating = false;
        if (this.run?.run_id === run.run_id) {
          this.run = { ...this.run, is_active: !remove };
        }
        this.loadRuns();
      },
      error: () => (this.activating = false)
    });
  }

  defaultLabel(run: MlRun): string {
    return run.scope === 'system' ? `Default for ${this.shortSystem(run.battery_system_id)}` : 'Base default';
  }

  /** Per-plant test scores of a run, with the plant names. */
  bySystem(run: MlRunDetail): { id: string; name: string; scores: MlSystemScores }[] {
    return Object.entries(run.metrics_by_system ?? {}).map(([id, scores]) => ({ id, name: this.systemName(Number(id)), scores }));
  }

  /** Plant defaults currently set (battery system scope). */
  get plantDefaults(): MlRun[] {
    return this.runs.filter((r) => r.is_active && r.scope === 'system');
  }

  // ---------------------------------------------------------------- history + comparison

  loadRuns(first = false): void {
    this.service.runs().subscribe({
      next: (runs) => {
        this.runs = runs;
        this.runsLoading = false;
        this.runsError = null;
        const known = new Set(runs.map((r) => r.run_id));
        this.compareIds = new Set([...this.compareIds].filter((id) => known.has(id)));
        if (this.finetuning && !this.parentRun) {
          this.applyParent();
        }
        if (first && !this.run) {
          const latest = runs.find((r) => r.status === 'COMPLETED');
          if (latest) {
            this.service.run(latest.run_id).subscribe((d) => {
              this.run = d;
              this.buildCurve();
              this.buildPredictions();
              this.buildImportance();
              this.buildSelection();
            });
          }
        }
        this.buildCompare();
      },
      error: () => {
        this.runsLoading = false;
        this.runsError = 'Could not load the model runs.';
      }
    });
  }

  get filteredRuns(): MlRun[] {
    return this.runs.filter(
      (r) =>
        (!this.historyFilter || r.model_type === this.historyFilter) &&
        (this.scopeFilter === '' ||
          (this.scopeFilter === 'base' ? r.scope === 'base' : r.battery_system_id === this.scopeFilter))
    );
  }

  /** Battery systems that have runs (for the history filter). */
  get runSystems(): number[] {
    return [...new Set(this.runs.filter((r) => r.scope === 'system').map((r) => r.battery_system_id as number))];
  }

  /** The base default run. */
  get activeRun(): MlRun | undefined {
    return this.runs.find((r) => r.is_active && r.scope === 'base');
  }

  /** The base run the SOH Estimator uses when no base default is set (runs are newest first). */
  get latestRun(): MlRun | undefined {
    return this.runs.find((r) => r.status === 'COMPLETED' && r.scope === 'base');
  }

  toggleCompare(run: MlRun, event: Event): void {
    event.stopPropagation();
    if (this.compareIds.has(run.run_id)) {
      this.compareIds.delete(run.run_id);
    } else {
      this.compareIds.add(run.run_id);
    }
    this.compareIds = new Set(this.compareIds);
    this.buildCompare();
  }

  get compared(): MlRun[] {
    return this.runs.filter((r) => this.compareIds.has(r.run_id)).sort((a, b) => a.run_id - b.run_id);
  }

  setCompareMetric(metric: MlMetricKey): void {
    this.compareMetric = metric;
    this.buildCompare();
  }

  metricLabel(key: string): string {
    return this.options?.metrics.find((m) => m.key === key)?.label ?? key;
  }

  /** The best value of a metric among the compared runs (for highlighting). */
  best(key: MlMetricKey): number | null {
    const spec = this.options?.metrics.find((m) => m.key === key);
    const values = this.compared.map((r) => r[key]).filter((v): v is number => v !== null && v !== undefined);
    if (!values.length || !spec) {
      return null;
    }
    return spec.better === 'higher' ? Math.max(...values) : Math.min(...values);
  }

  private buildCompare(): void {
    const runs = this.compared;
    if (runs.length < 2) {
      this.compareChart = undefined;
      return;
    }
    const key = this.compareMetric;
    this.compareChart = {
      type: 'bar',
      data: {
        labels: runs.map((r) => `#${r.run_id}${r.run_name ? ' ' + r.run_name : ''}`),
        datasets: [{
          label: this.metricLabel(key),
          data: runs.map((r) => r[key]),
          backgroundColor: runs.map((r) => MODEL_COLORS[r.model_type]),
          borderRadius: 4,
          borderSkipped: 'start',
          maxBarThickness: 44
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: axis(undefined, { grid: { display: false }, ticks: { color: INK_MUTED, font: { size: 11 }, autoSkip: false } }),
          y: axis(this.metricLabel(key), { grace: '12%' })
        },
        plugins: {
          legend: legend(false),
          valueLabels: { format: (v: number) => this.fmt(v, key) },
          tooltip: {
            ...tooltipBase(),
            callbacks: {
              label: (item: TooltipItem<'bar'>) => {
                const r = runs[item.dataIndex];
                return ` ${this.metricLabel(key)}: ${this.fmt(item.raw as number, key)} · ${this.modelLabel(r.model_type)}`;
              }
            }
          }
        }
      }
    } as AnyConfig;
  }

  confirmDelete(run: MlRun, event: Event): void {
    event.stopPropagation();
    this.confirmDeleteId = run.run_id;
  }

  deleteConfirmed(): void {
    const id = this.confirmDeleteId;
    if (id === null) {
      return;
    }
    this.service.deleteRun(id).subscribe({
      next: () => {
        this.confirmDeleteId = null;
        if (this.run?.run_id === id) {
          this.run = null;
        }
        this.loadRuns();
      },
      error: () => (this.confirmDeleteId = null)
    });
  }

  // ---------------------------------------------------------------- display

  fmt(value: number | null | undefined, key: string): string {
    if (value === null || value === undefined) {
      return '—';
    }
    if (key === 'r2' || key === 'explained_variance' || key === 'train_r2') {
      return value.toFixed(3);
    }
    if (key === 'mape_pct') {
      return `${value.toFixed(4)}%`;
    }
    return value.toFixed(4);
  }

  modelColor(model: string): string {
    return MODEL_COLORS[model as MlModelType] ?? INK;
  }

  groupLabel(key: string): string {
    return this.options?.feature_groups.find((g) => g.key === key)?.label ?? key;
  }

  featureList(group: { features: { label: string }[] }): string {
    return group.features.map((f) => f.label).join(', ');
  }

  groupLabels(run: MlRun): string {
    return run.feature_groups.map((g) => this.groupLabel(g)).join(', ');
  }

  paramSummary(run: MlRun): string {
    return Object.entries(run.params)
      .filter(([k]) => k !== 'early_stopping_rounds' || run.params[k])
      .map(([k, v]) => `${k}=${v}`)
      .join(', ');
  }

  plantTime(iso: string | null | undefined): string {
    return iso ? iso.slice(0, 16).replace('T', ' ') : '—';
  }
}
