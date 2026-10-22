import { CommonModule } from '@angular/common';
import { Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { ChartConfiguration } from 'chart.js';

import {
  WeakModuleResult,
  WeakPoint,
  WeakRun,
  WeakRunDetail,
  WeakSeriesPoint,
  WeakVerdict
} from '../../../core/models/weak-module.model';
import { WeakModuleService } from '../../../core/services/weak-module.service';
import { ChartCanvasComponent } from '../../telemetry/graphs/chart-canvas.component';

/* Colours (checked with the dataviz palette validator, light mode): Isolation Forest only, DBSCAN only, both.
   Normal rows are neutral grey; the heatmap uses one sequential hue (light -> dark) for the combined score. */
const IF_ONLY = '#6d5bd0';
const DB_ONLY = '#2aa198';
const BOTH = '#d9480f';
const NORMAL = 'rgba(120, 128, 140, 0.35)';
const INK = '#52565c';
const GRID = 'rgba(0, 0, 0, 0.06)';
const RAMP_LOW = [253, 240, 232];
const RAMP_HIGH = [138, 44, 11];

interface HeatCell {
  module: WeakModuleResult | null;
  position: number;
}

@Component({
  selector: 'app-weak-module-results',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink, ChartCanvasComponent],
  templateUrl: './weak-module-results.component.html',
  styleUrls: ['../model-training/model-training.component.scss', './weak-module-results.component.scss']
})
export class WeakModuleResultsComponent implements OnInit {
  runs: WeakRun[] = [];
  runId: number | null = null;
  run: WeakRunDetail | null = null;
  loading = true;
  error: string | null = null;

  points: WeakPoint[] = [];
  scatterChart: ChartConfiguration | null = null;
  heatRows: { pack: string; cells: HeatCell[] }[] = [];
  positions: number[] = [];

  showAll = false;
  selected: WeakModuleResult | null = null;
  series: WeakSeriesPoint[] = [];
  seriesLoading = false;
  voltageChart: ChartConfiguration | null = null;
  tempChart: ChartConfiguration | null = null;

  scoreFrom = '';
  scoreTo = '';
  scoring = false;
  scoreError: string | null = null;

  constructor(private service: WeakModuleService, private route: ActivatedRoute, private router: Router) {}

  ngOnInit(): void {
    const q = this.route.snapshot.queryParamMap.get('run');
    this.service.runs().subscribe({
      next: (runs) => {
        this.runs = runs.filter((r) => r.status === 'COMPLETED');
        const id = q ? Number(q) : this.runs[0]?.run_id ?? null;
        if (id) {
          this.selectRun(id);
        } else {
          this.loading = false;
        }
      },
      error: (err) => {
        this.error = err?.status === 0 ? 'Could not reach the ML service. Is it running on port 8100?' : 'Could not load the runs.';
        this.loading = false;
      }
    });
  }

  // ---------------------------------------------------------------- run

  selectRun(id: number): void {
    this.runId = id;
    this.loading = true;
    this.error = null;
    this.selected = null;
    this.router.navigate([], { relativeTo: this.route, queryParams: { run: id }, replaceUrl: true });
    this.service.run(id).subscribe({
      next: (run) => {
        this.run = run;
        this.loading = false;
        this.buildHeatmap();
        this.scoreFrom = '';
        this.scoreTo = '';
        const firstWeak = run.modules.find((m) => m.verdict !== 'NORMAL') ?? run.modules[0];
        if (firstWeak) {
          this.selectModule(firstWeak);
        }
      },
      error: (err) => {
        this.error = err?.error?.detail || 'Could not load this run.';
        this.loading = false;
      }
    });
    this.service.points(id).subscribe((points) => {
      this.points = points;
      this.buildScatter();
    });
  }

  runLabel(r: WeakRun): string {
    const name = r.run_name ? ` ${r.run_name}` : '';
    return `#${r.run_id}${name} · ${r.system_name} · ${r.date_from ?? 'start'} → ${r.date_to ?? 'end'} · ${r.n_weak ?? 0} weak / ${r.n_suspect ?? 0} suspect`;
  }

  get flagged(): WeakModuleResult[] {
    const mods = this.run?.modules ?? [];
    return this.showAll ? mods : mods.filter((m) => m.verdict !== 'NORMAL');
  }

  get agreement(): number | null {
    const v = this.run?.feature_stats?.['_agreement'];
    return typeof v === 'number' ? v : null;
  }

  get minSamples(): number | null {
    const v = this.run?.feature_stats?.['_min_samples_used'];
    return typeof v === 'number' ? v : null;
  }

  // ---------------------------------------------------------------- heatmap

  private buildHeatmap(): void {
    const mods = this.run?.modules ?? [];
    const packs = Array.from(new Set(mods.map((m) => m.pack_number))).sort();
    const maxPos = Math.max(0, ...mods.map((m) => m.position ?? 0));
    this.positions = Array.from({ length: maxPos }, (_, i) => i + 1);
    this.heatRows = packs.map((pack) => ({
      pack,
      cells: this.positions.map((position) => ({
        position,
        module: mods.find((m) => m.pack_number === pack && m.position === position) ?? null
      }))
    }));
  }

  heatColor(score: number): string {
    const t = Math.max(0, Math.min(1, score));
    const c = RAMP_LOW.map((lo, i) => Math.round(lo + (RAMP_HIGH[i] - lo) * t));
    return `rgb(${c[0]}, ${c[1]}, ${c[2]})`;
  }

  heatInk(score: number): string {
    return score > 0.45 ? '#fff' : '#1f2328';
  }

  packShort(pack: string): string {
    const m = pack.match(/PACK-(\d+)/i);
    return m ? `Pack ${Number(m[1])}` : pack;
  }

  // ---------------------------------------------------------------- scatter

  private buildScatter(): void {
    const serial = new Map((this.run?.modules ?? []).map((m) => [m.module_id, m.serial_number]));
    const groups: Record<string, { x: number; y: number; label: string }[]> = { normal: [], if: [], db: [], both: [] };
    for (const p of this.points) {
      const noise = p.db_label === -1;
      const key = p.if_flag && noise ? 'both' : p.if_flag ? 'if' : noise ? 'db' : 'normal';
      groups[key].push({
        x: p.features['v_dev_pack_mv'] ?? p.features['v_dev_sys_mv'] ?? 0,
        y: p.features['t_dev_pack_c'] ?? p.features['t_dev_sys_c'] ?? 0,
        label: `${serial.get(p.module_id) ?? p.module_id} · ${p.bucket.slice(0, 16).replace('T', ' ')}`
      });
    }
    const ds = (label: string, data: { x: number; y: number; label: string }[], color: string, r: number) => ({
      label: `${label} (${data.length})`, data, backgroundColor: color, borderColor: color, pointRadius: r, pointHoverRadius: r + 3
    });
    this.scatterChart = {
      type: 'scatter',
      data: {
        datasets: [
          ds('Normal', groups['normal'], NORMAL, 3),
          ds('Isolation Forest only', groups['if'], IF_ONLY, 4),
          ds('DBSCAN noise only', groups['db'], DB_ONLY, 4),
          ds('Both models', groups['both'], BOTH, 5)
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        plugins: {
          legend: { position: 'top', align: 'end', labels: { color: INK, usePointStyle: true, boxWidth: 8 } },
          tooltip: {
            callbacks: {
              label: (ctx) => {
                const raw = ctx.raw as { x: number; y: number; label: string };
                return `${raw.label}: ${raw.x.toFixed(1)} mV, ${raw.y.toFixed(2)} °C`;
              }
            }
          }
        },
        scales: {
          x: { title: { display: true, text: 'Voltage vs pack (mV)', color: INK }, grid: { color: GRID }, ticks: { color: INK } },
          y: { title: { display: true, text: 'Temperature vs pack (°C)', color: INK }, grid: { color: GRID }, ticks: { color: INK } }
        }
      }
    } as ChartConfiguration;
  }

  // ---------------------------------------------------------------- drill-down

  selectModule(m: WeakModuleResult): void {
    if (!this.runId) {
      return;
    }
    this.selected = m;
    this.seriesLoading = true;
    this.service.series(this.runId, m.module_id, this.run?.grain === 'hour' ? 'hour' : 'hour').subscribe({
      next: (series) => {
        this.series = series;
        this.seriesLoading = false;
        this.voltageChart = this.bandChart(series, 'v_dev_pack_mv', 'v_p10', 'v_p90', 'mV');
        this.tempChart = this.bandChart(series, 't_dev_pack_c', 't_p10', 't_p90', '°C');
      },
      error: () => {
        this.series = [];
        this.seriesLoading = false;
      }
    });
  }

  private bandChart(series: WeakSeriesPoint[], key: keyof WeakSeriesPoint, lo: keyof WeakSeriesPoint,
                    hi: keyof WeakSeriesPoint, unit: string): ChartConfiguration {
    const labels = series.map((p) => `${p.bucket.slice(8, 10)}/${p.bucket.slice(5, 7)} ${p.bucket.slice(11, 13)}h`);
    const color = this.selected?.verdict === 'WEAK' ? BOTH : this.selected?.verdict === 'SUSPECT' ? IF_ONLY : '#3b82f6';
    return {
      type: 'line',
      data: {
        labels,
        datasets: [
          { label: 'Pack p10', data: series.map((p) => p[lo] as number), borderColor: 'transparent', pointRadius: 0, fill: false },
          { label: 'Other modules of the pack (p10–p90)', data: series.map((p) => p[hi] as number), borderColor: 'transparent',
            backgroundColor: 'rgba(120, 128, 140, 0.18)', pointRadius: 0, fill: '-1' },
          { label: this.selected?.serial_number ?? 'Module', data: series.map((p) => p[key] as number), borderColor: color,
            backgroundColor: color, borderWidth: 2, pointRadius: 0, fill: false }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { position: 'top', align: 'end', labels: { color: INK, boxWidth: 12, filter: (item) => item.text !== 'Pack p10' } },
          tooltip: { callbacks: { label: (ctx) => ctx.dataset.label === 'Pack p10' ? '' :
            `${ctx.dataset.label}: ${(ctx.parsed.y ?? 0).toFixed(unit === 'mV' ? 1 : 2)} ${unit}` } }
        },
        scales: {
          x: { ticks: { color: INK, maxTicksLimit: 7, maxRotation: 0, autoSkipPadding: 16 }, grid: { display: false } },
          y: { title: { display: true, text: `Deviation from pack (${unit})`, color: INK }, grid: { color: GRID }, ticks: { color: INK } }
        }
      }
    } as ChartConfiguration;
  }

  // ---------------------------------------------------------------- score a new period

  scoreNew(): void {
    if (!this.run || this.run.run_kind !== 'train') {
      return;
    }
    this.scoring = true;
    this.scoreError = null;
    this.service.score(this.run.run_id, { date_from: this.scoreFrom || null, date_to: this.scoreTo || null, run_name: null })
      .subscribe({
        next: (run) => {
          this.scoring = false;
          this.runs = [run, ...this.runs];
          this.selectRun(run.run_id);
        },
        error: (err) => {
          const d = err?.error?.detail;
          this.scoreError = typeof d === 'string' ? d : d?.message || 'Scoring failed.';
          this.scoring = false;
        }
      });
  }

  // ---------------------------------------------------------------- display

  verdictLabel(v: WeakVerdict): string {
    return v === 'WEAK' ? 'Weak' : v === 'SUSPECT' ? 'Suspect' : 'Normal';
  }

  pct(v: number | null | undefined): string {
    return v === null || v === undefined ? '—' : `${Math.round(v * 100)}%`;
  }

  day(iso: string | null): string {
    return iso ? iso.slice(0, 10) : '—';
  }
}
