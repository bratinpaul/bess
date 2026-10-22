import { CommonModule } from '@angular/common';
import { Component, OnInit, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { ChartConfiguration } from 'chart.js';
import { forkJoin } from 'rxjs';

import {
  MvAlarm,
  MvContributors,
  MvEpisode,
  MvModelKey,
  MvOptions,
  MvRun,
  MvTimelinePoint
} from '../../../core/models/mv-anomaly.model';
import { MvAnomalyService } from '../../../core/services/mv-anomaly.service';
import { ChartCanvasComponent } from '../../telemetry/graphs/chart-canvas.component';
import { MV_MODEL_COLORS, contributorChart, ms, pct, ruleLabel, signalChart, timelineChart } from '../mv-anomaly-shared/mv-charts';

const SIGNAL_COLORS = ['#2f6fed', '#e8830c', '#12a37f'];

/** Multivariate anomaly detection - results: score timeline vs alarms, model comparison, what drives the flags,
 * episodes (explained by an alarm or new) and a signal drill-down per episode. */
@Component({
  selector: 'app-mv-anomaly',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink, ChartCanvasComponent],
  templateUrl: './mv-anomaly.component.html',
  styleUrls: ['../model-training/model-training.component.scss', './mv-anomaly.component.scss']
})
export class MvAnomalyComponent implements OnInit {
  private api = inject(MvAnomalyService);
  private route = inject(ActivatedRoute);
  private router = inject(Router);

  readonly colors = MV_MODEL_COLORS;
  readonly pct = pct;
  readonly ruleLabel = ruleLabel;

  options: MvOptions | null = null;
  error: string | null = null;

  systemId: number | null = null;
  runs: MvRun[] = [];
  runId: number | null = null;
  run: MvRun | null = null;
  loading = false;

  timeline: MvTimelinePoint[] = [];
  alarms: MvAlarm[] = [];
  episodes: MvEpisode[] = [];
  contributors: MvContributors | null = null;

  timelineConfig: ChartConfiguration | null = null;
  contributorConfig: ChartConfiguration | null = null;
  showOthers = false;
  episodeFilter: 'all' | 'new' | 'explained' | 'rules' = 'all';

  selectedEpisode: MvEpisode | null = null;
  signalCharts: { label: string; config: ChartConfiguration }[] = [];
  signalsLoading = false;
  signalsError: string | null = null;

  liveRunning = false;
  liveMessage: string | null = null;
  liveHours = 24;

  ngOnInit(): void {
    this.api.options().subscribe({
      next: (o) => {
        this.options = o;
        const runParam = Number(this.route.snapshot.queryParamMap.get('run'));
        if (runParam) {
          this.openRun(runParam);
        } else {
          this.loadRuns(null);
        }
      },
      error: () => (this.error = 'Could not reach the ML service on port 8100.')
    });
  }

  // --- selection ---------------------------------------------------------------------------------------------------

  loadRuns(systemId: number | null, pick?: number): void {
    this.api.runs(systemId ?? undefined).subscribe({
      next: (runs) => {
        const done = runs.filter((r) => r.status === 'COMPLETED');
        if (systemId === null) {
          // no system chosen: the newest system with a model
          const first = done.find((r) => r.run_kind === 'train');
          if (!first) {
            this.runs = [];
            return;
          }
          this.systemId = first.system_id;
          this.loadRuns(first.system_id);
          return;
        }
        this.systemId = systemId;
        this.runs = done;
        const target = pick ?? done.find((r) => r.is_default)?.run_id ?? done[0]?.run_id;
        if (target && target !== this.runId) {
          this.selectRun(target);
        }
      },
      error: () => (this.error = 'Could not load the runs.')
    });
  }

  selectSystem(id: number): void {
    this.runId = null;
    this.run = null;
    this.loadRuns(id);
  }

  openRun(id: number): void {
    this.api.run(id).subscribe({
      next: (r) => {
        this.systemId = r.system_id;
        this.loadRuns(r.system_id, id);
      },
      error: () => this.loadRuns(null)
    });
  }

  selectRun(id: number): void {
    this.runId = id;
    this.router.navigate([], { relativeTo: this.route, queryParams: { run: id }, replaceUrl: true });
    this.loading = true;
    this.selectedEpisode = null;
    this.signalCharts = [];
    forkJoin({
      run: this.api.run(id),
      timeline: this.api.timeline(id),
      alarms: this.api.alarms(id),
      episodes: this.api.episodes(id),
      contributors: this.api.contributors(id)
    }).subscribe({
      next: (d) => {
        this.run = d.run;
        this.timeline = d.timeline;
        this.alarms = d.alarms;
        this.episodes = d.episodes;
        this.contributors = d.contributors;
        this.loading = false;
        this.buildCharts();
      },
      error: () => {
        this.loading = false;
        this.error = 'Could not load this run.';
      }
    });
  }

  // --- derived -----------------------------------------------------------------------------------------------------

  /** The model settings: a train run's own, or the model a score / live run used. */
  get modelParams() {
    return this.run?.run_kind === 'train' ? this.run.params : this.run?.model?.params;
  }

  get primary(): MvModelKey {
    return (this.modelParams?.primary as MvModelKey) ?? 'pca';
  }

  get models(): MvModelKey[] {
    return (this.modelParams?.models as MvModelKey[]) ?? [this.primary];
  }

  get limits(): Record<string, number> {
    const t = this.run?.run_kind === 'train' ? this.run.thresholds : this.run?.model?.thresholds;
    return t?.limits ?? {};
  }

  get metrics() {
    return this.run?.run_kind === 'train' ? this.run.metrics : null;
  }

  get modelRows() {
    const m = this.metrics;
    return this.models.map((k) => ({ key: k, label: this.modelLabel(k), m: m?.[k] ?? null, limit: this.limits[k] ?? 1 }));
  }

  get spanFrom(): string | null {
    return this.timeline.length ? this.timeline[0].ts : null;
  }

  get spanTo(): string | null {
    return this.timeline.length ? this.timeline[this.timeline.length - 1].ts : null;
  }

  get explainedShare(): number | null {
    const model = this.episodes.filter((e) => e.model_flag);
    return model.length ? model.filter((e) => e.explained).length / model.length : null;
  }

  get filteredEpisodes(): MvEpisode[] {
    switch (this.episodeFilter) {
      case 'new':
        return this.episodes.filter((e) => e.model_flag && !e.explained);
      case 'explained':
        return this.episodes.filter((e) => e.explained);
      case 'rules':
        return this.episodes.filter((e) => e.rule_flags.length);
      default:
        return this.episodes;
    }
  }

  get labels(): Record<string, string> {
    return Object.fromEntries((this.options?.models ?? []).map((m) => [m.key, m.label]));
  }

  modelLabel(k: string | undefined): string {
    return this.options?.models.find((m) => m.key === k)?.label ?? k ?? '—';
  }

  runLabel(r: MvRun): string {
    const kind = r.run_kind === 'train' ? 'Model' : r.run_kind === 'score' ? `Score of #${r.parent_run_id}` : `Live of #${r.parent_run_id}`;
    const name = r.run_name ? ` · ${r.run_name}` : '';
    const live = r.is_default ? ' · live model' : '';
    return `#${r.run_id} ${kind}${name}${live}`;
  }

  duration(e: MvEpisode): string {
    const min = (ms(e.end) - ms(e.start)) / 60000;
    return min >= 120 ? `${(min / 60).toFixed(1)} h` : `${Math.round(min)} min`;
  }

  // --- charts ------------------------------------------------------------------------------------------------------

  buildCharts(): void {
    if (!this.timeline.length) {
      this.timelineConfig = null;
    } else {
      this.timelineConfig = timelineChart(
        this.timeline,
        this.alarms,
        this.primary,
        this.limits[this.primary] ?? 1,
        this.run?.run_kind === 'train' ? this.run.eval_from : null,
        this.showOthers ? this.models.filter((k) => k !== this.primary) : [],
        this.labels
      );
    }
    const feats = (this.contributors?.features ?? []).slice(0, 10);
    this.contributorConfig = feats.length ? contributorChart(feats, MV_MODEL_COLORS[this.primary]) : null;
  }

  toggleOthers(): void {
    this.showOthers = !this.showOthers;
    this.buildCharts();
  }

  openEpisode(e: MvEpisode): void {
    this.selectedEpisode = e;
    this.signalCharts = [];
    this.signalsError = null;
    const keys = e.top_contributors.slice(0, 3).map((c) => c.feature);
    if (!keys.length || !this.runId) {
      return;
    }
    // the episode with 2 h of context on each side
    const s = ms(e.start);
    const end = ms(e.end);
    const pad = 2 * 3600_000;
    this.signalsLoading = true;
    this.api.signals(this.runId, new Date(s - pad).toISOString(), new Date(end + pad).toISOString(), keys).subscribe({
      next: (sig) => {
        this.signalsLoading = false;
        this.signalCharts = sig.features.map((f, i) => ({
          label: f.label,
          config: signalChart(sig.points, f.key, f.label, SIGNAL_COLORS[i % SIGNAL_COLORS.length], { s, e: end })
        }));
      },
      error: (err) => {
        this.signalsLoading = false;
        this.signalsError = err?.error?.detail || 'Could not load the signals.';
      }
    });
  }

  // --- actions -----------------------------------------------------------------------------------------------------

  scoreLatest(): void {
    if (!this.systemId) {
      return;
    }
    this.liveRunning = true;
    this.liveMessage = null;
    this.api.live(this.systemId, this.liveHours).subscribe({
      next: (res) => {
        this.liveRunning = false;
        const r = res[0];
        if (r?.status === 'ok' && r.live_run_id) {
          this.liveMessage = `Scored ${r.rows} intervals up to ${String(r.window_end).slice(0, 16).replace('T', ' ')} with model #${r.model_run_id}: ${r.flagged_intervals} flagged.`;
          this.loadRuns(this.systemId, r.live_run_id);
          this.selectRun(r.live_run_id);
        } else {
          this.liveMessage = r?.message ? `Not scored: ${r.message}` : 'Nothing scored.';
        }
      },
      error: (err) => {
        this.liveRunning = false;
        this.liveMessage = err?.error?.detail || 'Live scoring failed.';
      }
    });
  }
}
