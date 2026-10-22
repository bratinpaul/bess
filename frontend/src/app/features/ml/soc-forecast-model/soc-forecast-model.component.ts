import { CommonModule } from '@angular/common';
import { Component, OnDestroy, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { TooltipItem } from 'chart.js';

import { SocMethod, SocOptions, SocRun, SocRunDetail, SocScores, SocUnit } from '../../../core/models/soc-forecast.model';
import { SocForecastService } from '../../../core/services/soc-forecast.service';
import { ChartCanvasComponent } from '../../telemetry/graphs/chart-canvas.component';
import { AnyConfig, axis, legend, tooltip } from '../price-forecast-shared/pf-charts';
import { METHOD_COLORS, METHOD_DASH, METHOD_LABELS, METHOD_ORDER } from '../soc-forecast-shared/soc-charts';

interface ScoreCol {
  key: keyof SocScores;
  label: string;
  better: 'low' | 'high' | 'target80';
  digits: number;
  help: string;
}

const COLS: ScoreCol[] = [
  { key: 'mae', label: 'MAE', better: 'low', digits: 2, help: 'Mean absolute error of P50 over every step (SOC points)' },
  { key: 'rmse', label: 'RMSE', better: 'low', digits: 2, help: 'Root mean squared error (SOC points)' },
  { key: 'mae_1h', label: 'MAE 1 h', better: 'low', digits: 2, help: 'MAE one hour ahead' },
  { key: 'mae_4h', label: 'MAE 4 h', better: 'low', digits: 2, help: 'MAE four hours ahead' },
  { key: 'mae_end', label: 'MAE end', better: 'low', digits: 2, help: 'MAE at the end of the horizon' },
  { key: 'coverage_pct', label: 'P10–P90 cover %', better: 'target80', digits: 1, help: 'Share of steps inside P10–P90 (80 % is right)' },
  { key: 'width', label: 'Width', better: 'low', digits: 2, help: 'Mean P90 − P10 (SOC points)' },
  { key: 'skill_pct', label: 'Skill vs hold %', better: 'high', digits: 1, help: '1 − MAE / MAE of holding SOC' },
  { key: 'drawdown_mae', label: 'Drawdown err', better: 'low', digits: 2, help: 'Error of the lowest SOC over the horizon (P50 vs actual)' },
  { key: 'breach_pct', label: 'Breach %', better: 'low', digits: 1, help: 'Origins whose actual lowest SOC fell below the P10 lowest SOC (worst case under-estimated)' }
];

/** ML Model -> SOC Forecast: build the SOC trajectory models (physics + LightGBM residual) and compare the methods. */
@Component({
  selector: 'app-soc-forecast-model',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink, ChartCanvasComponent],
  templateUrl: './soc-forecast-model.component.html',
  styleUrls: ['../model-training/model-training.component.scss', '../price-forecast-model/price-forecast-model.component.scss']
})
export class SocForecastModelComponent implements OnInit, OnDestroy {
  readonly cols = COLS;
  readonly colors = METHOD_COLORS;
  readonly labels = METHOD_LABELS;
  readonly methods = METHOD_ORDER;

  options: SocOptions | null = null;
  optionsError: string | null = null;
  emsIds = new Set<number>();
  dateFrom = '';
  dateTo = '';
  horizon = 12;
  testPct = 20;
  originStep = 60;
  trainStep = 60;
  trainHorizonStep = 3;
  limitsMode: 'learned' | 'manual' = 'learned';
  socMin = 10;
  socMax = 90;
  gbm: Record<string, number> = {};
  showGbm = false;
  runName = '';
  makeDefault = true;

  training = false;
  trainError: string | null = null;
  elapsed = 0;
  private timer?: ReturnType<typeof setInterval>;

  runs: SocRun[] = [];
  runsLoading = true;
  run: SocRunDetail | null = null;
  runLoading = false;
  stepChart?: AnyConfig;
  importanceChart?: AnyConfig;
  importanceHeight = 300;
  importanceSource = 'scheduled';

  constructor(private service: SocForecastService, private route: ActivatedRoute, private router: Router) {}

  ngOnInit(): void {
    this.service.options().subscribe({
      next: (o) => {
        this.options = o;
        this.emsIds = new Set(o.units.filter((u) => u.readings > 0).map((u) => u.ems_id));
        this.horizon = o.defaults.horizon_h;
        this.testPct = o.defaults.test_fraction * 100;
        this.originStep = o.defaults.origin_step_min;
        this.trainStep = o.defaults.train_origin_step_min;
        this.trainHorizonStep = o.defaults.train_horizon_step;
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

  resetGbm(): void {
    this.gbm = Object.fromEntries((this.options?.gbm_params ?? []).map((p) => [p.name, p.default]));
  }

  unitLabel(u: SocUnit): string {
    return `${u.site_name ?? u.system_name ?? 'EMS ' + u.ems_id} · ${u.ems_code}`;
  }

  shortUnit(id: number | string): string {
    const u = this.options?.units.find((x) => x.ems_id === Number(id));
    return u?.site_name?.replace(/ BESS Site| Grid Storage Site| Site/, '') ?? `EMS ${id}`;
  }

  toggleUnit(u: SocUnit): void {
    if (!u.readings) {
      return;
    }
    this.emsIds.has(u.ems_id) ? this.emsIds.delete(u.ems_id) : this.emsIds.add(u.ems_id);
    this.emsIds = new Set(this.emsIds);
  }

  get problem(): string | null {
    if (!this.emsIds.size) {
      return 'Choose at least one EMS';
    }
    if (this.limitsMode === 'manual' && !(Number(this.socMax) > Number(this.socMin))) {
      return 'SOC max must be above SOC min';
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
    const manual = this.limitsMode === 'manual';
    this.service
      .train({
        ems_ids: Array.from(this.emsIds),
        date_from: this.dateFrom || null,
        date_to: this.dateTo || null,
        horizon_h: Number(this.horizon),
        test_fraction: Number(this.testPct) / 100,
        origin_step_min: Number(this.originStep),
        train_origin_step_min: Number(this.trainStep),
        train_horizon_step: Number(this.trainHorizonStep),
        soc_min: manual ? Number(this.socMin) : null,
        soc_max: manual ? Number(this.socMax) : null,
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
        this.buildCharts();
      },
      error: () => (this.runLoading = false)
    });
  }

  makeDefaultRun(r: SocRun, event?: Event): void {
    event?.stopPropagation();
    this.service.makeDefault(r.run_id).subscribe(() => this.loadRuns(this.run?.run_id ?? null));
  }

  deleteRun(r: SocRun, event: Event): void {
    event.stopPropagation();
    if (!window.confirm(`Delete SOC forecast run #${r.run_id}, its scores and backtests?`)) {
      return;
    }
    this.service.deleteRun(r.run_id).subscribe(() => {
      if (this.run?.run_id === r.run_id) {
        this.run = null;
      }
      this.loadRuns();
    });
  }

  reuse(r: SocRunDetail): void {
    this.emsIds = new Set(r.ems_ids);
    this.dateFrom = r.date_from ?? '';
    this.dateTo = r.date_to ?? '';
    this.horizon = r.horizon_h;
    this.testPct = r.test_fraction * 100;
    this.originStep = r.origin_step_min;
    this.trainStep = r.params['train_origin_step_min'] ?? 60;
    this.trainHorizonStep = r.params['train_horizon_step'] ?? 3;
    this.limitsMode = r.params['soc_min'] !== null && r.params['soc_min'] !== undefined ? 'manual' : 'learned';
    if (this.limitsMode === 'manual') {
      this.socMin = r.params['soc_min'];
      this.socMax = r.params['soc_max'];
    }
    this.gbm = { ...(r.params['gbm'] ?? {}) };
    this.runName = '';
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  // ---------------------------------------------------------------- scores

  get methodKeys(): SocMethod[] {
    return METHOD_ORDER.filter((k) => this.run?.metrics?.[k]);
  }

  cell(k: SocMethod, c: ScoreCol): string {
    const v = this.run?.metrics?.[k]?.[c.key];
    return typeof v === 'number' && Number.isFinite(v) ? v.toFixed(c.digits) : '—';
  }

  isBest(k: SocMethod, c: ScoreCol): boolean {
    const m = this.run?.metrics;
    if (!m) {
      return false;
    }
    const vals = this.methodKeys.map((x) => [x, m[x]?.[c.key]] as const).filter(([, v]) => typeof v === 'number') as [SocMethod, number][];
    if (!vals.length) {
      return false;
    }
    const rank = (v: number) => (c.better === 'low' ? v : c.better === 'high' ? -v : Math.abs(v - 80));
    return vals.reduce((b, x) => (rank(x[1]) < rank(b[1]) ? x : b))[0] === k;
  }

  get physicsRows(): { ems: string; p: any; cov: number | null; split: any }[] {
    const r = this.run?.results;
    return Object.entries(r?.physics ?? {}).map(([ems, p]) => ({ ems, p, cov: r?.schedule_coverage[ems] ?? null, split: r?.split[ems] }));
  }

  num(v: number | null | undefined, d = 2): string {
    return typeof v === 'number' && Number.isFinite(v) ? v.toFixed(d) : '—';
  }

  plantTime(ts: string | null | undefined): string {
    return ts ? ts.replace('T', ' ').slice(0, 16) : '—';
  }

  window(r: SocRun): string {
    return `${r.date_from ?? 'start'} → ${r.date_to ?? 'end'}`;
  }

  duration(ms: number | null): string {
    return ms === null ? '' : ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
  }

  // ---------------------------------------------------------------- charts

  buildCharts(): void {
    const byStep = this.run?.results?.mae_by_step;
    if (byStep) {
      const every = this.run!.results!.step_every_min;
      const n = Math.max(...Object.values(byStep).map((v) => v.length));
      this.stepChart = {
        type: 'line',
        data: {
          labels: Array.from({ length: n }, (_, i) => ((i * every + 5) / 60).toFixed(2)),
          datasets: this.methodKeys.map((k) => ({
            label: METHOD_LABELS[k],
            data: byStep[k] ?? [],
            borderColor: METHOD_COLORS[k],
            backgroundColor: METHOD_COLORS[k],
            borderDash: METHOD_DASH[k],
            borderWidth: k === this.run?.best_method ? 3 : 2,
            pointRadius: 0,
            tension: 0.2
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
                label: (ctx: TooltipItem<'line'>) => `${ctx.dataset.label}: ${(ctx.parsed.y as number)?.toFixed(2)} SOC pts`
              }
            }
          },
          scales: {
            x: axis('Hours ahead', { ticks: { color: '#6b6f76', maxTicksLimit: 13 } }),
            y: { ...axis('MAE (SOC points)'), type: 'logarithmic' }
          }
        }
      } as AnyConfig;
    } else {
      this.stepChart = undefined;
    }
    this.buildImportance();
  }

  buildImportance(): void {
    const imp = this.run?.results?.importance?.[this.importanceSource];
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
      data: { labels: entries.map(([f]) => f), datasets: [{ data: entries.map(([, v]) => v * 100), backgroundColor: '#eb6834', borderRadius: 4, barThickness: 12 }] },
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
