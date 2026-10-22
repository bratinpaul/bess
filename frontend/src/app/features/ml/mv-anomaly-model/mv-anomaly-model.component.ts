import { CommonModule } from '@angular/common';
import { Component, OnDestroy, OnInit, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';

import { MvModelKey, MvOptions, MvPreview, MvRun, MvSystem, MvTrainRequest } from '../../../core/models/mv-anomaly.model';
import { MvAnomalyService } from '../../../core/services/mv-anomaly.service';
import { MV_MODEL_COLORS, MV_REASON_LABELS, pct } from '../mv-anomaly-shared/mv-charts';

/** Multivariate anomaly detection - model builder: data window, features, detectors, regime handling, thresholds. */
@Component({
  selector: 'app-mv-anomaly-model',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  templateUrl: './mv-anomaly-model.component.html',
  styleUrls: ['../model-training/model-training.component.scss', './mv-anomaly-model.component.scss']
})
export class MvAnomalyModelComponent implements OnInit, OnDestroy {
  private api = inject(MvAnomalyService);
  private router = inject(Router);

  readonly colors = MV_MODEL_COLORS;
  readonly reasonLabels = MV_REASON_LABELS;
  readonly pct = pct;

  options: MvOptions | null = null;
  optionsError: string | null = null;

  systemId: number | null = null;
  dateFrom = '';
  dateTo = '';
  evalFraction = 0.3;
  groups = new Set<string>();

  selected = new Set<MvModelKey>();
  primary: MvModelKey = 'pca';
  params: Record<string, Record<string, number>> = {};

  regimeStrategy: 'feature' | 'separate' = 'feature';
  minRegimeRows = 300;
  thresholdPct = 99.5;
  thresholdMode: 'percentile' | 'best_f1' = 'percentile';
  smoothWindow = 3;
  debounce = 3;
  frozenIntervals = 6;
  alarmPadMin = 30;
  commissioningDays = 7;
  excludeAlarmLevel = true;
  topK = 3;
  runName = '';
  makeDefault = false;

  preview: MvPreview | null = null;
  previewing = false;
  previewError: string | null = null;
  private previewTimer: ReturnType<typeof setTimeout> | null = null;

  running = false;
  runError: string | null = null;

  runs: MvRun[] = [];
  runsLoading = false;
  filterSystem: number | null = null;

  // score another window with a built model
  scoreFor: MvRun | null = null;
  scoreFrom = '';
  scoreTo = '';
  scoring = false;
  scoreError: string | null = null;

  ngOnInit(): void {
    this.api.options().subscribe({
      next: (o) => {
        this.options = o;
        this.resetParams();
        const best = [...o.systems].sort((a, b) => b.rows - a.rows)[0];
        if (best) {
          this.selectSystem(best.battery_system_id);
        }
      },
      error: () => (this.optionsError = 'Could not reach the ML service on port 8100.')
    });
    this.loadRuns();
  }

  ngOnDestroy(): void {
    if (this.previewTimer) {
      clearTimeout(this.previewTimer);
    }
  }

  get system(): MvSystem | undefined {
    return this.options?.systems.find((s) => s.battery_system_id === this.systemId);
  }

  get featureCount(): number {
    return (this.options?.feature_groups ?? []).filter((g) => this.groups.has(g.key)).reduce((n, g) => n + g.features.length, 0);
  }

  get selectedModels() {
    return (this.options?.models ?? []).filter((m) => this.selected.has(m.key));
  }

  get canRun(): boolean {
    return !!this.systemId && this.selected.size > 0 && this.groups.size > 0 && this.selected.has(this.primary) && !this.running;
  }

  get filteredRuns(): MvRun[] {
    return this.filterSystem ? this.runs.filter((r) => r.system_id === this.filterSystem) : this.runs;
  }

  resetParams(): void {
    const o = this.options;
    if (!o) {
      return;
    }
    const d = o.defaults;
    this.groups = new Set(o.feature_groups.map((g) => g.key));
    this.selected = new Set(d.models);
    this.primary = d.primary;
    this.params = Object.fromEntries(o.models.map((m) => [m.key, { ...m.defaults }]));
    this.regimeStrategy = d.regime_strategy;
    this.minRegimeRows = d.min_regime_rows;
    this.evalFraction = d.eval_fraction;
    this.thresholdPct = d.threshold_pct;
    this.thresholdMode = d.threshold_mode;
    this.smoothWindow = d.smooth_window;
    this.debounce = d.debounce;
    this.frozenIntervals = d.frozen_intervals;
    this.alarmPadMin = d.alarm_pad_min;
    this.commissioningDays = d.commissioning_days;
    this.topK = d.top_k;
    this.excludeAlarmLevel = true;
    this.schedulePreview();
  }

  selectSystem(id: number): void {
    this.systemId = id;
    const s = this.system;
    this.dateFrom = s?.date_from ?? '';
    this.dateTo = s?.date_to ?? '';
    this.schedulePreview();
  }

  toggleGroup(key: string): void {
    this.groups.has(key) ? this.groups.delete(key) : this.groups.add(key);
  }

  toggleModel(key: MvModelKey): void {
    if (this.selected.has(key)) {
      this.selected.delete(key);
      if (this.primary === key) {
        this.primary = [...this.selected][0] ?? key;
      }
    } else {
      this.selected.add(key);
    }
  }

  schedulePreview(): void {
    if (this.previewTimer) {
      clearTimeout(this.previewTimer);
    }
    this.previewTimer = setTimeout(() => this.loadPreview(), 400);
  }

  private window() {
    return {
      system_id: this.systemId!,
      date_from: this.dateFrom || null,
      date_to: this.dateTo || null,
      eval_fraction: this.evalFraction,
      frozen_intervals: this.frozenIntervals,
      alarm_pad_min: this.alarmPadMin,
      commissioning_days: this.commissioningDays,
      exclude_alarm_level: this.excludeAlarmLevel
    };
  }

  loadPreview(): void {
    if (!this.systemId) {
      return;
    }
    this.previewing = true;
    this.previewError = null;
    this.api.preview(this.window()).subscribe({
      next: (p) => {
        this.preview = p;
        this.previewing = false;
      },
      error: (err) => {
        this.preview = null;
        this.previewing = false;
        this.previewError = err?.error?.detail || 'Could not count the rows.';
      }
    });
  }

  excludedEntries(p: MvPreview): { key: string; n: number }[] {
    return Object.entries(p.excluded).map(([key, n]) => ({ key, n }));
  }

  regimeEntries(p: MvPreview): { key: string; n: number }[] {
    return Object.entries(p.regimes).map(([key, n]) => ({ key, n }));
  }

  run(): void {
    if (!this.canRun) {
      return;
    }
    const body: MvTrainRequest = {
      ...this.window(),
      models: [...this.selected],
      primary: this.primary,
      model_params: Object.fromEntries([...this.selected].map((k) => [k, this.params[k] ?? {}])),
      feature_groups: [...this.groups],
      regime_strategy: this.regimeStrategy,
      min_regime_rows: this.minRegimeRows,
      threshold_pct: this.thresholdPct,
      threshold_mode: this.thresholdMode,
      smooth_window: this.smoothWindow,
      debounce: this.debounce,
      top_k: this.topK,
      run_name: this.runName.trim() || null,
      make_default: this.makeDefault
    };
    this.running = true;
    this.runError = null;
    this.api.train(body).subscribe({
      next: (r) => {
        this.running = false;
        this.loadRuns();
        this.router.navigate(['/ml/mv-anomaly'], { queryParams: { run: r.run_id } });
      },
      error: (err) => {
        this.running = false;
        const d = err?.error?.detail;
        this.runError = (typeof d === 'string' ? d : d?.message) || 'Training failed. Is the ML service running?';
        this.loadRuns();
      }
    });
  }

  loadRuns(): void {
    this.runsLoading = true;
    this.api.runs().subscribe({
      next: (r) => {
        this.runs = r;
        this.runsLoading = false;
      },
      error: () => (this.runsLoading = false)
    });
  }

  open(r: MvRun): void {
    if (r.status === 'COMPLETED') {
      this.router.navigate(['/ml/mv-anomaly'], { queryParams: { run: r.run_id } });
    }
  }

  setDefault(r: MvRun, ev: Event): void {
    ev.stopPropagation();
    this.api.makeDefault(r.run_id).subscribe({ next: () => this.loadRuns() });
  }

  deleteRun(r: MvRun, ev: Event): void {
    ev.stopPropagation();
    const what = r.run_kind === 'train' ? 'this model and every score / live run made with it' : 'this run';
    if (!confirm(`Delete run #${r.run_id} - ${what}?`)) {
      return;
    }
    this.api.deleteRun(r.run_id).subscribe({ next: () => this.loadRuns() });
  }

  startScore(r: MvRun, ev: Event): void {
    ev.stopPropagation();
    this.scoreFor = r;
    this.scoreError = null;
    const s = this.options?.systems.find((x) => x.battery_system_id === r.system_id);
    this.scoreFrom = s?.date_from ?? '';
    this.scoreTo = s?.date_to ?? '';
  }

  runScore(): void {
    if (!this.scoreFor) {
      return;
    }
    this.scoring = true;
    this.scoreError = null;
    this.api
      .score(this.scoreFor.run_id, { date_from: this.scoreFrom || null, date_to: this.scoreTo || null, run_name: null })
      .subscribe({
        next: (r) => {
          this.scoring = false;
          this.scoreFor = null;
          this.router.navigate(['/ml/mv-anomaly'], { queryParams: { run: r.run_id } });
        },
        error: (err) => {
          this.scoring = false;
          const d = err?.error?.detail;
          this.scoreError = (typeof d === 'string' ? d : d?.message) || 'Scoring failed.';
        }
      });
  }

  primaryMetric(r: MvRun, key: 'f1' | 'auc' | 'event_recall'): number | null {
    const p = r.params?.primary;
    return p && r.metrics?.[p] ? r.metrics[p][key] : null;
  }

  window_(r: MvRun): string {
    if (r.run_kind === 'live') {
      return r.summary?.['window_end'] ? `latest → ${String(r.summary['window_end']).slice(0, 16).replace('T', ' ')}` : 'live';
    }
    return `${r.date_from ?? 'start'} → ${r.date_to ?? 'end'}`;
  }

  duration(ms: number | null): string {
    if (ms === null || ms === undefined) {
      return '—';
    }
    return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
  }

  modelLabel(key: string | undefined): string {
    return this.options?.models.find((m) => m.key === key)?.label ?? key ?? '—';
  }
}
