import { CommonModule } from '@angular/common';
import { Component, OnInit, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { ChartConfiguration } from 'chart.js';

import { ArbOptions, ArbStudy, ArbStudyRequest } from '../../../core/models/arbitrage-optimizer.model';
import { ArbitrageOptimizerService } from '../../../core/services/arbitrage-optimizer.service';
import { ChartCanvasComponent } from '../../telemetry/graphs/chart-canvas.component';

const TICK = '#6b6f76';
const GRID = '#eceef0';

const CHECK_LABELS: Record<string, string> = {
  soc_in_band: 'SOC stays inside the SOC band',
  no_simultaneous: 'No interval charges and discharges at once',
  cycle_cap: 'Daily cycles within the cap',
  profit_le_oracle: 'Profit ≤ perfect-foresight oracle',
  losses_present: 'Round-trip losses appear (discharge < charge)',
  deg_cost_bites: 'With degradation cost = 0 the optimizer cycles more',
  pack_settlement_reproduced: "Pack's realized P&L reproduced by the cost model"
};

/** ML Model -> Arbitrage Optimizer: run a dispatch-optimization study (MILP backtest over a date range) and review its
 *  results, sanity checks and per-day profit against the oracle and the data pack's realized runs. */
@Component({
  selector: 'app-arbitrage-optimizer',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink, ChartCanvasComponent],
  templateUrl: './arbitrage-optimizer.component.html',
  styleUrl: './arbitrage-optimizer.component.scss'
})
export class ArbitrageOptimizerComponent implements OnInit {
  private service = inject(ArbitrageOptimizerService);

  options: ArbOptions | null = null;
  optionsError: string | null = null;
  form: ArbStudyRequest | null = null;
  asCapText = '';

  running = false;
  runError: string | null = null;

  studies: ArbStudy[] = [];
  selected: ArbStudy | null = null;
  dayChart: ChartConfiguration | null = null;
  toDelete: ArbStudy | null = null;

  readonly checkLabels = CHECK_LABELS;

  ngOnInit(): void {
    this.service.options().subscribe({
      next: (o) => {
        this.options = o;
        this.form = { ...o.defaults };
      },
      error: () => (this.optionsError = 'Could not reach the ML service (port 8100).')
    });
    this.loadStudies(true);
  }

  loadStudies(selectLatest = false): void {
    this.service.studies().subscribe({
      next: (s) => {
        this.studies = s;
        const latest = s.find((x) => x.status === 'COMPLETED');
        if (selectLatest && latest && !this.selected) {
          this.open(latest.study_id);
        }
      },
      error: () => (this.studies = [])
    });
  }

  get system() {
    return this.options?.systems.find((s) => s.system_id === this.form?.system_id) ?? null;
  }

  run(): void {
    if (!this.form) {
      return;
    }
    const cap = this.asCapText.trim();
    const body: ArbStudyRequest = { ...this.form, as_max_mw: cap === '' ? null : Number(cap), study_name: this.form.study_name?.trim() || null };
    this.running = true;
    this.runError = null;
    this.service.runStudy(body).subscribe({
      next: (s) => {
        this.running = false;
        this.show(s);
        this.loadStudies();
      },
      error: (err) => {
        this.running = false;
        const d = err?.error?.detail;
        this.runError = typeof d === 'string' ? d : d?.message || 'The study failed.';
        this.loadStudies();
      }
    });
  }

  open(id: number): void {
    this.service.study(id).subscribe({ next: (s) => this.show(s) });
  }

  private show(s: ArbStudy): void {
    this.selected = s;
    this.dayChart = this.buildDayChart(s);
  }

  confirmDelete(s: ArbStudy): void {
    this.toDelete = s;
  }

  deleteConfirmed(): void {
    const s = this.toDelete;
    if (!s) {
      return;
    }
    this.service.deleteStudy(s.study_id).subscribe({
      next: () => {
        this.toDelete = null;
        if (this.selected?.study_id === s.study_id) {
          this.selected = null;
          this.dayChart = null;
        }
        this.loadStudies();
      }
    });
  }

  m(key: string): number | null {
    const v = this.selected?.metrics?.[key];
    return typeof v === 'number' ? v : null;
  }

  num(v: number | null | undefined, d = 2): string {
    return v === null || v === undefined || !Number.isFinite(v) ? '—' : v.toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });
  }

  get checkEntries(): { key: string; label: string; ok: boolean }[] {
    const c = this.selected?.checks?.checks ?? {};
    return Object.entries(c).map(([key, ok]) => ({ key, label: CHECK_LABELS[key] ?? key, ok: !!ok }));
  }

  detail(key: string): number | null {
    const v = this.selected?.checks?.details?.[key];
    return typeof v === 'number' ? v : null;
  }

  get packRef(): { logged?: Record<string, number>; model?: Record<string, number>; max_diff?: number } | null {
    return (this.selected?.checks?.details?.['pack_reference'] as never) ?? null;
  }

  dayTotal(d: { net_usd: number; checks: Record<string, unknown> }): number {
    return d.net_usd + (Number(d.checks?.['as_usd']) || 0);
  }

  private buildDayChart(s: ArbStudy): ChartConfiguration | null {
    const days = s.days ?? [];
    if (!days.length) {
      return null;
    }
    const labels = days.map((d) => d.kpi_date.slice(5));
    const bar = (label: string, data: (number | null)[], color: string) => ({
      label, data, backgroundColor: color, borderRadius: 3, maxBarThickness: 14, categoryPercentage: 0.8, barPercentage: 0.9
    });
    return {
      type: 'bar',
      data: {
        labels,
        datasets: [
          bar('Policy (energy net + AS)', days.map((d) => this.dayTotal(d)), '#2f6fed'),
          bar('Perfect-foresight oracle', days.map((d) => d.oracle_net_usd), '#b9c7e8'),
          bar('Pack realized (energy net)', days.map((d) => d.pack_net_usd), '#e8830c')
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        interaction: { mode: 'index', intersect: false },
        plugins: { legend: { position: 'bottom', labels: { boxWidth: 12, color: TICK } } },
        scales: {
          x: { grid: { display: false }, ticks: { color: TICK, autoSkipPadding: 8 } },
          y: { grid: { color: GRID }, border: { display: false }, ticks: { color: TICK }, title: { display: true, text: 'USD / day', color: TICK } }
        }
      }
    };
  }
}
