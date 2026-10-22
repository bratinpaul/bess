import { CommonModule } from '@angular/common';
import { Component, OnDestroy, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { TooltipItem } from 'chart.js';

import {
  LabelSource,
  SocEstMethod,
  SocEstOptions,
  SocEstRun,
  SocEstRunDetail,
  SocEstScope,
  SocEstScore,
  SocEstSystem,
  SocEstSystemResult
} from '../../../core/models/soc-estimation.model';
import { SocEstimationService } from '../../../core/services/soc-estimation.service';
import { ChartCanvasComponent } from '../../telemetry/graphs/chart-canvas.component';
import { AnyConfig, axis, legend, tooltip } from '../price-forecast-shared/pf-charts';
import { BANDED, EST_COLORS, EST_DASH, EST_LABELS, EST_ORDER, SCOPE_LABELS, SCOPE_ORDER } from '../soc-estimation-shared/soc-est-charts';

interface ScoreCol {
  key: keyof SocEstScore;
  label: string;
  better: 'low' | 'high' | 'target80' | 'zero';
  digits: number;
  help: string;
}

const COLS: ScoreCol[] = [
  { key: 'n', label: 'Rows', better: 'high', digits: 0, help: 'Rows scored in this scope (test period)' },
  { key: 'rmse', label: 'RMSE', better: 'low', digits: 2, help: 'Root mean squared error (SOC points)' },
  { key: 'mae', label: 'MAE', better: 'low', digits: 2, help: 'Mean absolute error (SOC points)' },
  { key: 'bias', label: 'Bias', better: 'zero', digits: 2, help: 'Mean error (estimate − truth); positive = reads high' },
  { key: 'p95_abs', label: 'P95 |err|', better: 'low', digits: 2, help: '95th percentile of the absolute error' },
  { key: 'max_error', label: 'Max |err|', better: 'low', digits: 2, help: 'Largest absolute error' },
  { key: 'coverage_pct', label: 'P10–P90 cover %', better: 'target80', digits: 1, help: 'Share of truths inside P10–P90 (80 % is right)' },
  { key: 'width', label: 'Width', better: 'low', digits: 2, help: 'Mean P90 − P10 (SOC points)' },
  { key: 'skill_pct', label: 'Skill vs coulomb %', better: 'high', digits: 1, help: '1 − RMSE / RMSE of raw coulomb counting' }
];

/** ML Model -> SOC Estimation: build the SOC estimator (EKF + LightGBM corrections) and compare it with coulomb
 *  counting and the naïve OCV lookup against the anchors and the flat mid-SOC region. */
@Component({
  selector: 'app-soc-estimation-model',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink, ChartCanvasComponent],
  templateUrl: './soc-estimation-model.component.html',
  styleUrls: ['../model-training/model-training.component.scss', '../price-forecast-model/price-forecast-model.component.scss']
})
export class SocEstimationModelComponent implements OnInit, OnDestroy {
  readonly cols = COLS;
  readonly colors = EST_COLORS;
  readonly labels = EST_LABELS;
  readonly methods = EST_ORDER;
  readonly scopeLabels = SCOPE_LABELS;
  readonly scopes = SCOPE_ORDER;

  options: SocEstOptions | null = null;
  optionsError: string | null = null;
  systemIds = new Set<number>();
  dateFrom = '';
  dateTo = '';
  testPct = 25;
  labelSource: LabelSource = 'anchors';
  tuneEkf = true;
  fullChargeReset = true;
  ekf: Record<string, number> = {};
  gbm: Record<string, number> = {};
  showEkf = false;
  showGbm = false;
  runName = '';
  makeDefault = true;

  training = false;
  trainError: string | null = null;
  elapsed = 0;
  private timer?: ReturnType<typeof setInterval>;

  runs: SocEstRun[] = [];
  runsLoading = true;
  run: SocEstRunDetail | null = null;
  runLoading = false;
  scope: SocEstScope = 'dense_flat';
  bandChart?: AnyConfig;
  importanceChart?: AnyConfig;
  importanceHeight = 300;
  importanceModel: 'hybrid' | 'gbm' = 'hybrid';

  constructor(private service: SocEstimationService, private route: ActivatedRoute, private router: Router) {}

  ngOnInit(): void {
    this.service.options().subscribe({
      next: (o) => {
        this.options = o;
        this.systemIds = new Set(o.systems.filter((s) => s.readings > 0 && s.anchors > 0).map((s) => s.system_id));
        this.testPct = o.defaults.test_fraction * 100;
        this.labelSource = o.defaults.label_source;
        this.tuneEkf = o.defaults.tune_ekf;
        this.fullChargeReset = o.defaults.full_charge_reset;
        this.resetEkf();
        this.resetGbm();
      },
      error: (err) =>
        (this.optionsError = err?.status === 0 ? 'Could not reach the ML service. Is it running on port 8100?' : 'Could not load the options.')
    });
    this.loadRuns(Number(this.route.snapshot.queryParamMap.get('run')) || null);
  }

  ngOnDestroy(): void {
    clearInterval(this.timer);
  }

  resetEkf(): void {
    this.ekf = Object.fromEntries((this.options?.ekf_params ?? []).map((p) => [p.name, p.default]));
  }

  resetGbm(): void {
    this.gbm = Object.fromEntries((this.options?.gbm_params ?? []).map((p) => [p.name, p.default]));
  }

  systemLabel(s: SocEstSystem): string {
    return `${s.system_name}${s.site_name ? ' · ' + s.site_name : ''}`;
  }

  shortSystem(id: number | string): string {
    return this.options?.systems.find((x) => x.system_id === Number(id))?.system_name ?? `system ${id}`;
  }

  toggleSystem(s: SocEstSystem): void {
    if (!s.readings) {
      return;
    }
    this.systemIds.has(s.system_id) ? this.systemIds.delete(s.system_id) : this.systemIds.add(s.system_id);
    this.systemIds = new Set(this.systemIds);
  }

  get problem(): string | null {
    if (!this.systemIds.size) {
      return 'Choose at least one battery system';
    }
    if (this.dateFrom && this.dateTo && this.dateTo < this.dateFrom) {
      return 'The end date is before the start date';
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
    this.service
      .train({
        system_ids: Array.from(this.systemIds),
        date_from: this.dateFrom || null,
        date_to: this.dateTo || null,
        test_fraction: Number(this.testPct) / 100,
        label_source: this.labelSource,
        tune_ekf: this.tuneEkf,
        full_charge_reset: this.fullChargeReset,
        ekf_params: this.ekf,
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
        this.scope = run.primary_scope ?? 'anchors';
        this.buildCharts();
      },
      error: () => (this.runLoading = false)
    });
  }

  makeDefaultRun(r: SocEstRun, event?: Event): void {
    event?.stopPropagation();
    this.service.makeDefault(r.run_id).subscribe(() => this.loadRuns(this.run?.run_id ?? null));
  }

  deleteRun(r: SocEstRun, event: Event): void {
    event.stopPropagation();
    if (!window.confirm(`Delete SOC estimation run #${r.run_id}, its scores, timeline and estimator state?`)) {
      return;
    }
    this.service.deleteRun(r.run_id).subscribe(() => {
      if (this.run?.run_id === r.run_id) {
        this.run = null;
      }
      this.loadRuns();
    });
  }

  reuse(r: SocEstRunDetail): void {
    this.systemIds = new Set(r.system_ids);
    this.dateFrom = r.date_from ?? '';
    this.dateTo = r.date_to ?? '';
    this.testPct = r.test_fraction * 100;
    this.labelSource = r.params?.['label_source_requested'] ?? r.label_source;
    this.tuneEkf = r.params?.['tune_ekf'] ?? true;
    this.fullChargeReset = r.params?.['full_charge_reset'] ?? true;
    this.ekf = { ...(r.params?.['ekf'] ?? {}) };
    this.gbm = { ...(r.params?.['gbm'] ?? {}) };
    this.runName = '';
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  // ---------------------------------------------------------------- scores

  get methodKeys(): SocEstMethod[] {
    return EST_ORDER.filter((k) => this.run?.metrics?.[k]);
  }

  get scopeKeys(): SocEstScope[] {
    return SCOPE_ORDER.filter((s) => (this.run?.metrics?.coulomb?.[s]?.n ?? 0) > 0);
  }

  score(k: SocEstMethod, s: SocEstScope): SocEstScore | undefined {
    return this.run?.metrics?.[k]?.[s];
  }

  cell(k: SocEstMethod, c: ScoreCol, s: SocEstScope = this.scope): string {
    const v = this.score(k, s)?.[c.key];
    if (c.key === 'coverage_pct' || c.key === 'width') {
      if (!BANDED.includes(k)) {
        return '—';
      }
    }
    return typeof v === 'number' && Number.isFinite(v) ? v.toFixed(c.digits) : '—';
  }

  isBest(k: SocEstMethod, c: ScoreCol, s: SocEstScope = this.scope): boolean {
    if (c.key === 'n') {
      return false;
    }
    const vals = this.methodKeys
      .filter((x) => !(c.key === 'coverage_pct' || c.key === 'width') || BANDED.includes(x))
      .map((x) => [x, this.score(x, s)?.[c.key]] as const)
      .filter(([, v]) => typeof v === 'number') as [SocEstMethod, number][];
    if (!vals.length) {
      return false;
    }
    const rank = (v: number) => (c.better === 'low' ? v : c.better === 'high' ? -v : c.better === 'zero' ? Math.abs(v) : Math.abs(v - 80));
    return vals.reduce((b, x) => (rank(x[1]) < rank(b[1]) ? x : b))[0] === k;
  }

  readonly rmseCol = COLS[1];

  get systemRows(): { id: string; r: SocEstSystemResult }[] {
    return Object.entries(this.run?.results?.ekf ?? {}).map(([id, r]) => ({ id, r }));
  }

  topTrials(r: SocEstSystemResult) {
    return [...(r.tuning ?? [])].filter((t) => t.rmse !== null).sort((a, b) => (a.rmse ?? 1e9) - (b.rmse ?? 1e9)).slice(0, 5);
  }

  num(v: number | null | undefined, d = 2): string {
    return typeof v === 'number' && Number.isFinite(v) ? v.toFixed(d) : '—';
  }

  plantTime(ts: string | null | undefined): string {
    return ts ? ts.replace('T', ' ').slice(0, 16) : '—';
  }

  window(r: SocEstRun): string {
    return `${r.date_from ?? 'start'} → ${r.date_to ?? 'end'}`;
  }

  duration(ms: number | null): string {
    return ms === null ? '' : ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
  }

  // ---------------------------------------------------------------- charts

  buildCharts(): void {
    const byBand = this.run?.results?.rmse_by_band;
    const edges = this.run?.results?.band_edges ?? [];
    if (byBand && Object.keys(byBand).length) {
      const labels = edges.slice(0, -1).map((e, i) => `${e}–${edges[i + 1]}`);
      this.bandChart = {
        type: 'line',
        data: {
          labels,
          datasets: this.methodKeys
            .filter((k) => byBand[k])
            .map((k) => ({
              label: EST_LABELS[k],
              data: byBand[k]!.map((v) => (v === null ? null : Math.max(v, 0.005))),
              borderColor: EST_COLORS[k],
              backgroundColor: EST_COLORS[k],
              borderDash: EST_DASH[k],
              borderWidth: k === this.run?.best_method ? 3 : 2,
              pointRadius: 3,
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
                title: (items: TooltipItem<'line'>[]) => `True SOC ${items[0]?.label} %`,
                label: (ctx: TooltipItem<'line'>) => `${ctx.dataset.label}: RMSE ${(ctx.parsed.y as number)?.toFixed(2)} SOC pts`
              }
            }
          },
          scales: {
            x: axis('True SOC band (%)'),
            y: { ...axis('RMSE (SOC points, log)'), type: 'logarithmic' }
          }
        }
      } as AnyConfig;
    } else {
      this.bandChart = undefined;
    }
    this.buildImportance();
  }

  buildImportance(): void {
    const imp = this.run?.results?.importance?.[this.importanceModel];
    if (!imp) {
      this.importanceChart = undefined;
      return;
    }
    const entries = Object.entries(imp)
      .filter(([, v]) => v > 0.002)
      .sort((a, b) => b[1] - a[1]);
    this.importanceHeight = Math.max(160, entries.length * 22 + 40);
    this.importanceChart = {
      type: 'bar',
      data: {
        labels: entries.map(([f]) => f),
        datasets: [{ data: entries.map(([, v]) => v * 100), backgroundColor: EST_COLORS[this.importanceModel], borderRadius: 4, barThickness: 12 }]
      },
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
