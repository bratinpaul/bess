import { CommonModule } from '@angular/common';
import { Component, OnInit, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { ChartConfiguration, ChartDataset } from 'chart.js';

import { HeatLedgerRow, HeatPoint, HeatRun, HeatSystemSummary } from '../../../core/models/heat-load.model';
import { HeatLoadService } from '../../../core/services/heat-load.service';
import { ChartCanvasComponent } from '../../telemetry/graphs/chart-canvas.component';

/** Heat terms in stack order on the validated categorical slots 1-6; slot 7 marks the calibrated model. */
const COLOR: Record<string, string> = {
  q_batt_irr_kw: '#2a78d6', q_batt_rev_kw: '#eb6834', q_pcs_kw: '#1baf7a', q_aux_kw: '#eda100', q_solar_kw: '#e87ba4',
  q_env_kw: '#008300', model: '#6250d6'
};
const LABEL: Record<string, string> = {
  q_batt_irr_kw: 'Battery ohmic / overpotential', q_batt_rev_kw: 'Battery entropic', q_pcs_kw: 'PCS conversion',
  q_aux_kw: 'Aux electronics', q_solar_kw: 'Solar gain', q_env_kw: 'Envelope'
};
const TERMS = ['q_batt_irr_kw', 'q_batt_rev_kw', 'q_pcs_kw', 'q_aux_kw', 'q_solar_kw', 'q_env_kw'];
const DESIGN_TERMS: { key: string; label: string; color: string }[] = [
  { key: 'battery_irreversible', label: 'Battery ohmic / overpotential (EOL)', color: COLOR['q_batt_irr_kw'] },
  { key: 'battery_entropic', label: 'Battery entropic', color: COLOR['q_batt_rev_kw'] },
  { key: 'pcs', label: 'PCS conversion', color: COLOR['q_pcs_kw'] },
  { key: 'aux', label: 'Aux electronics', color: COLOR['q_aux_kw'] },
  { key: 'solar', label: 'Solar gain', color: COLOR['q_solar_kw'] },
  { key: 'envelope', label: 'Envelope', color: COLOR['q_env_kw'] },
  { key: 'constant', label: 'Constant (calibration)', color: '#b9b8b0' }
];
const INK = '#52514e';
const MUTED = '#9a998f';
const GRID = '#eceef0';
const SURFACE = '#ffffff';
const BAND = 'rgba(42, 120, 214, 0.16)';

type Tab = 'balance' | 'design' | 'forecast' | 'ledger';

/** Insights -> Forecasting -> Heat Load & Thermal Design: the enclosure heat balance against the measured reference,
 *  the design sizing (peak at end-of-life resistance, margin, N + 1, duty curve) and the operational forecast. */
@Component({
  selector: 'app-heat-load',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink, ChartCanvasComponent],
  templateUrl: './heat-load.component.html',
  styleUrl: './heat-load.component.scss'
})
export class HeatLoadComponent implements OnInit {
  private service = inject(HeatLoadService);
  private route = inject(ActivatedRoute);

  runs: HeatRun[] = [];
  runId: number | null = null;
  run: HeatRun | null = null;
  systemId: number | null = null;
  tab: Tab = 'balance';
  error: string | null = null;
  showWarnings = false;

  day = '';
  ledger: HeatLedgerRow[] = [];
  horizon = 60;
  fcFrom = '';
  fcTo = '';
  issues: string[] = [];
  issue = '';
  points: HeatPoint[] = [];
  trajectory: HeatPoint[] = [];

  dayChart: ChartConfiguration | null = null;
  dailyChart: ChartConfiguration | null = null;
  peakChart: ChartConfiguration | null = null;
  designChart: ChartConfiguration | null = null;
  bracketChart: ChartConfiguration | null = null;
  ldcChart: ChartConfiguration | null = null;
  histChart: ChartConfiguration | null = null;
  maeChart: ChartConfiguration | null = null;
  seriesChart: ChartConfiguration | null = null;
  planChart: ChartConfiguration | null = null;
  trajChart: ChartConfiguration | null = null;

  readonly terms = TERMS;
  readonly label = LABEL;
  readonly color = COLOR;
  readonly designTerms = DESIGN_TERMS;
  readonly Math = Math;

  ngOnInit(): void {
    const qp = this.route.snapshot.queryParamMap;
    const wanted = Number(qp.get('run')) || null;
    this.service.runs().subscribe({
      next: (r) => {
        this.runs = r.filter((x) => x.status === 'COMPLETED');
        const pick = this.runs.find((x) => x.run_id === wanted) ?? this.runs[0];
        if (pick) {
          this.selectRun(pick.run_id);
        }
      },
      error: () => (this.error = 'Could not reach the ML service (port 8100).')
    });
  }

  runLabel(r: HeatRun): string {
    return `#${r.run_id} ${r.run_name || 'Heat-load run'} · ${r.date_from} → ${r.date_to} · ${r.system_ids.length} system(s)`;
  }

  selectRun(id: number): void {
    this.runId = id;
    this.service.run(id).subscribe({
      next: (r) => {
        this.run = r;
        this.systemId = r.system_ids[0] ?? null;
        this.onSystem();
      },
      error: () => (this.error = `Run #${id} could not be loaded.`)
    });
  }

  get systems(): { id: number; name: string }[] {
    return (this.run?.system_ids ?? []).map((id) => ({ id, name: this.run?.summary?.systems?.[String(id)]?.system_name ?? `#${id}` }));
  }

  get s(): HeatSystemSummary | null {
    return this.systemId !== null ? this.run?.summary?.systems?.[String(this.systemId)] ?? null : null;
  }

  get warnings(): string[] {
    const name = this.s?.system_name;
    return (this.run?.warnings ?? []).filter((w) => !name || w.startsWith(name));
  }

  get days(): string[] {
    return (this.s?.daily ?? []).map((d) => String(d['day']));
  }

  onSystem(): void {
    const s = this.s;
    if (!s) {
      return;
    }
    // the day with the highest measured peak in the window
    const daily = s.daily ?? [];
    const top = [...daily].sort((a, b) => Number(b['measured_peak_kw']) - Number(a['measured_peak_kw']))[0];
    this.day = top ? String(top['day']) : '';
    this.fcFrom = s.test_from.slice(0, 10);
    const d = new Date(this.fcFrom + 'T00:00:00');
    d.setDate(d.getDate() + 2);
    this.fcTo = d.toISOString().slice(0, 10);
    this.horizon = Number(Object.keys(s.forecast.by_horizon ?? {}).find((h) => h === '60') ?? Object.keys(s.forecast.by_horizon ?? {})[0] ?? 60);
    this.buildDaily();
    this.buildDesign();
    this.buildMae();
    this.loadDay();
    this.loadSeries();
    this.service.issues(this.runId!, this.systemId!).subscribe({
      next: (i) => {
        this.issues = i;
        this.issue = i.find((x) => x.includes('T16:00')) ?? i[Math.floor(i.length / 2)] ?? '';
        this.loadTrajectory();
      }
    });
  }

  setTab(t: Tab): void {
    this.tab = t;
  }

  // ---------------------------------------------------------------- chart helpers

  private axes(y: string, x: Record<string, unknown> = {}, yExtra: Record<string, unknown> = {}) {
    return {
      x: { grid: { display: false }, ticks: { color: MUTED, maxRotation: 0, autoSkipPadding: 14 }, ...x },
      y: { grid: { color: GRID }, border: { display: false }, ticks: { color: MUTED }, title: { display: true, text: y, color: MUTED }, ...yExtra }
    };
  }

  private cfg(type: 'bar' | 'line', datasets: ChartDataset[], labels: (string | number)[] | undefined, scales: unknown, legend = true,
              tooltip?: Record<string, unknown>): ChartConfiguration {
    return {
      type,
      data: { labels, datasets } as ChartConfiguration['data'],
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        interaction: { mode: 'index', intersect: false },
        plugins: { legend: { display: legend, position: 'bottom', labels: { boxWidth: 12, color: INK } }, ...(tooltip ? { tooltip } : {}) },
        scales: scales as never
      }
    } as ChartConfiguration;
  }

  private line(label: string, data: (number | null)[], color: string, extra: Record<string, unknown> = {}): ChartDataset {
    return { type: 'line', label, data, borderColor: color, backgroundColor: color, borderWidth: 2, pointRadius: 0, pointHoverRadius: 4,
      tension: 0, spanGaps: false, ...extra } as ChartDataset;
  }

  private bar(label: string, data: (number | null)[], color: string | string[], extra: Record<string, unknown> = {}): ChartDataset {
    return { type: 'bar', label, data, backgroundColor: color, borderColor: SURFACE, borderWidth: { top: 1, bottom: 0, left: 0, right: 0 },
      borderSkipped: false, borderRadius: 1, maxBarThickness: 22, categoryPercentage: 0.9, barPercentage: 0.95, ...extra } as ChartDataset;
  }

  private stackedScales(y: string) {
    return {
      x: { stacked: true, grid: { display: false }, ticks: { color: MUTED, maxRotation: 0, autoSkipPadding: 14 } },
      y: { stacked: true, grid: { color: GRID }, border: { display: false }, ticks: { color: MUTED }, title: { display: true, text: y, color: MUTED } }
    };
  }

  // ---------------------------------------------------------------- heat balance

  loadDay(): void {
    if (!this.runId || this.systemId === null || !this.day) {
      return;
    }
    this.service.ledger(this.runId, this.systemId, this.day).subscribe({
      next: (rows) => {
        this.ledger = rows;
        this.buildDayChart();
      }
    });
  }

  stepDay(delta: number): void {
    const i = this.days.indexOf(this.day);
    const next = this.days[i + delta];
    if (next) {
      this.day = next;
      this.loadDay();
    }
  }

  private buildDayChart(): void {
    const rows = this.ledger;
    if (!rows.length) {
      this.dayChart = null;
      return;
    }
    const labels = rows.map((r) => r.ts.slice(11, 16));
    const ds: ChartDataset[] = TERMS.map((t) =>
      this.bar(LABEL[t], rows.map((r) => r[t as keyof HeatLedgerRow] as number | null), COLOR[t], { stack: 'q', maxBarThickness: 8, categoryPercentage: 1, barPercentage: 0.92, borderWidth: 0, borderRadius: 0 }));
    // lines get their own stacks, else the stacked axis piles them on top of the bars
    ds.push(this.line('Measured reference', rows.map((r) => r.measured_kw), INK, { stack: 'measured', order: -2 }));
    ds.push(this.line('Calibrated model', rows.map((r) => r.q_model_kw), COLOR['model'], { stack: 'model', borderDash: [5, 4], order: -1 }));
    this.dayChart = this.cfg('bar', ds, labels, this.stackedScales('heat (kW thermal)'));
  }

  private buildDaily(): void {
    const d = this.s?.daily ?? [];
    if (!d.length) {
      this.dailyChart = this.peakChart = null;
      return;
    }
    const labels = d.map((x) => String(x['day']).slice(5));
    const map: Record<string, string> = { q_batt_irr_kw: 'q_batt_kw', q_batt_rev_kw: 'q_rev_kw', q_pcs_kw: 'q_pcs_kw', q_aux_kw: 'q_aux_kw', q_solar_kw: 'q_solar_kw', q_env_kw: 'q_env_kw' };
    const ds: ChartDataset[] = TERMS.map((t) => this.bar(LABEL[t], d.map((x) => Number(x[map[t]])), COLOR[t], { stack: 'q' }));
    ds.push(this.line('Measured reference (mean)', d.map((x) => Number(x['measured_mean_kw'])), INK, { stack: 'measured', pointRadius: 2, order: -1 }));
    this.dailyChart = this.cfg('bar', ds, labels, this.stackedScales('daily mean heat (kW)'));
    this.peakChart = this.cfg('line', [
      this.line('Measured peak', d.map((x) => Number(x['measured_peak_kw'])), INK, { pointRadius: 2 }),
      this.line('Calibrated model peak', d.map((x) => Number(x['q_model_peak_kw'])), COLOR['model'], { borderDash: [5, 4], pointRadius: 2 }),
      this.line('Nameplate physics peak', d.map((x) => Number(x['q_total_peak_kw'])), COLOR['q_batt_irr_kw'], { borderDash: [2, 3], pointRadius: 0 })
    ], labels, this.axes('daily peak heat (kW)'));
  }

  get dirRows(): { key: string; label: string; v: (d: string) => number | null }[] {
    const g = (d: string, k: string) => (this.s?.direction?.[d] as unknown as Record<string, number> | undefined)?.[k] ?? null;
    return [
      ...TERMS.map((t) => ({ key: t, label: LABEL[t], v: (d: string) => g(d, t) })),
      { key: 'q_storage_kw', label: '− Stored in the thermal mass', v: (d: string) => { const x = g(d, 'q_storage_kw'); return x === null ? null : -x; } },
      { key: 'q_total_kw', label: 'Physics total (nameplate)', v: (d: string) => g(d, 'q_total_kw') },
      { key: 'q_total_no_entropic_kw', label: 'Physics total without entropic', v: (d: string) => g(d, 'q_total_no_entropic_kw') },
      { key: 'q_model_kw', label: 'Calibrated model', v: (d: string) => g(d, 'q_model_kw') },
      { key: 'measured_kw', label: 'Measured reference', v: (d: string) => g(d, 'measured_kw') }
    ];
  }

  // ---------------------------------------------------------------- design

  private buildDesign(): void {
    const d = this.s?.design;
    if (!d) {
      this.designChart = this.bracketChart = this.ldcChart = this.histChart = null;
      return;
    }
    const cases = ['CHARGE', 'DISCHARGE'] as const;
    this.designChart = this.cfg('bar', DESIGN_TERMS.map((t) =>
      this.bar(t.label, cases.map((c) => d.cases[c].terms[t.key as keyof typeof d.cases.CHARGE.terms]), t.color, { stack: 'd', maxBarThickness: 46 })),
      ['Charge at rated power', 'Discharge at rated power'], this.stackedScales('heat at the design condition (kW)'));

    const o = d.observed;
    const items: { label: string; v: number | null; c: string }[] = [
      { label: 'Measured peak (window)', v: Number(o['measured_peak_kw']), c: MUTED },
      { label: 'Design peak at BOL', v: d.q_peak_bol_kw, c: '#86b6ef' },
      { label: 'Design peak at EOL', v: d.q_peak_kw, c: COLOR['q_batt_irr_kw'] },
      { label: `Required (+${d.margin_pct} % margin)`, v: d.required_capacity_kw, c: INK },
      { label: 'Installed (units running × rating)', v: o['installed_capacity_kw'] === undefined ? null : Number(o['installed_capacity_kw']), c: '#c9c8c1' },
      { label: 'Peak cooling delivered (telemetry)', v: Number(o['cooling_delivered_peak_kw']), c: '#c9c8c1' }
    ];
    this.bracketChart = this.cfg('bar', [{ type: 'bar', label: 'kW', data: items.map((i) => i.v), backgroundColor: items.map((i) => i.c), borderRadius: 2, maxBarThickness: 22 } as unknown as ChartDataset],
      items.map((i) => i.label), {}, false);
    const opts = this.bracketChart.options as Record<string, unknown>;
    opts['indexAxis'] = 'y';
    opts['scales'] = {
      x: { grace: '10%', grid: { color: GRID }, border: { display: false }, ticks: { color: MUTED }, title: { display: true, text: 'kW thermal', color: MUTED } },
      y: { grid: { display: false }, ticks: { color: INK } }
    };
    (opts['plugins'] as Record<string, unknown>)['valueLabels'] = { format: (v: number) => this.num(v, 1) };

    const ldc = d.duty.load_duration;
    const labels = ldc.map((x) => x.pct_time);
    this.ldcChart = this.cfg('line', [
      this.line('Calibrated model', ldc.map((x) => x.q_kw), COLOR['model']),
      this.line('Measured reference', ldc.map((x) => x.measured_kw), INK),
      this.line(`Required capacity ${this.num(d.required_capacity_kw, 0)} kW`, ldc.map(() => d.required_capacity_kw), MUTED, { borderDash: [5, 4], borderWidth: 1.5 })
    ], labels, this.axes('heat load (kW)', { title: { display: true, text: '% of time the load is exceeded', color: MUTED }, ticks: { color: MUTED, maxTicksLimit: 11, maxRotation: 0 } }));

    const h = d.duty.histogram.filter((x) => x.hours > 0 || x.from_kw <= d.required_capacity_kw);
    this.histChart = this.cfg('bar', [this.bar('Hours', h.map((x) => x.hours), COLOR['q_batt_irr_kw'], { maxBarThickness: 26 })],
      h.map((x) => `${x.from_kw.toFixed(0)}–${x.to_kw.toFixed(0)}`), this.axes('hours in the window', { title: { display: true, text: 'heat load band (kW)', color: MUTED } }), false);
  }

  cond(key: string): number | string | boolean | null {
    return this.s?.design?.condition?.[key] ?? null;
  }

  condNum(key: string): number | null {
    const v = this.cond(key);
    return typeof v === 'number' ? v : null;
  }

  obs(key: string): number | null {
    const v = this.s?.design?.observed?.[key];
    return typeof v === 'number' ? v : null;
  }

  // ---------------------------------------------------------------- forecast

  get horizons(): number[] {
    return Object.keys(this.s?.forecast?.by_horizon ?? {}).map(Number).sort((a, b) => a - b);
  }

  private buildMae(): void {
    const by = this.s?.forecast?.by_horizon ?? {};
    const hs = this.horizons;
    if (!hs.length) {
      this.maeChart = null;
      return;
    }
    const g = (h: number, k: string) => (by[String(h)] as unknown as Record<string, number>)[k];
    this.maeChart = this.cfg('line', [
      this.line('Persistence', hs.map((h) => g(h, 'persistence_mae')), MUTED, { borderDash: [5, 4], pointRadius: 4 }),
      this.line('Physics (RC grey-box)', hs.map((h) => g(h, 'physics_mae')), COLOR['q_batt_irr_kw'], { pointRadius: 4 }),
      this.line('Hybrid P50', hs.map((h) => g(h, 'p50_mae')), COLOR['model'], { pointRadius: 4 })
    ], hs.map((h) => `${h} min`), this.axes('MAE (kW)'));
  }

  loadSeries(): void {
    if (!this.runId || this.systemId === null || !this.fcFrom) {
      return;
    }
    this.service.horizon(this.runId, this.systemId, this.horizon, this.fcFrom, this.fcTo || this.fcFrom).subscribe({
      next: (p) => {
        this.points = p;
        this.buildSeries();
      }
    });
  }

  private buildSeries(): void {
    const p = this.points;
    if (!p.length) {
      this.seriesChart = this.planChart = null;
      return;
    }
    const labels = p.map((x) => `${x.valid_at.slice(5, 10)} ${x.valid_at.slice(11, 16)}`);
    this.seriesChart = this.cfg('line', [
      this.line('P10', p.map((x) => x.p10_kw), 'rgba(0,0,0,0)', { pointRadius: 0, borderWidth: 0 }),
      this.line('P10–P90', p.map((x) => x.p90_kw), 'rgba(0,0,0,0)', { fill: '-1', backgroundColor: BAND, borderWidth: 0 }),
      this.line('Actual', p.map((x) => x.actual_kw), INK, { pointRadius: 2 }),
      this.line('Hybrid P50', p.map((x) => x.p50_kw), COLOR['model']),
      this.line('Physics', p.map((x) => x.physics_kw), COLOR['q_batt_irr_kw'], { borderDash: [2, 3], borderWidth: 1.5 }),
      this.line('Persistence', p.map((x) => x.persistence_kw), MUTED, { borderDash: [5, 4], borderWidth: 1.5 })
    ], labels, this.axes(`heat load ${this.horizon} min ahead (kW)`));
    const leg = (this.seriesChart.options!.plugins!.legend as Record<string, unknown>);
    leg['labels'] = { boxWidth: 12, color: INK, filter: (item: { text: string }) => item.text !== 'P10' };
    this.planChart = this.cfg('line', [this.line('Planned battery power at the target time', p.map((x) => x.plan_kw), COLOR['q_pcs_kw'], { stepped: true })],
      labels, this.axes('plan (kW)'), true);
  }

  loadTrajectory(): void {
    if (!this.runId || this.systemId === null || !this.issue) {
      return;
    }
    this.service.trajectory(this.runId, this.systemId, this.issue).subscribe({
      next: (t) => {
        this.trajectory = t;
        const labels = t.map((x) => `+${x.horizon_min} min`);
        this.trajChart = this.cfg('line', [
          this.line('P10', t.map((x) => x.p10_kw), 'rgba(0,0,0,0)', { borderWidth: 0 }),
          this.line('P10–P90', t.map((x) => x.p90_kw), 'rgba(0,0,0,0)', { fill: '-1', backgroundColor: BAND, borderWidth: 0 }),
          this.line('Actual', t.map((x) => x.actual_kw), INK, { pointRadius: 4 }),
          this.line('Hybrid P50', t.map((x) => x.p50_kw), COLOR['model'], { pointRadius: 4 }),
          this.line('Physics', t.map((x) => x.physics_kw), COLOR['q_batt_irr_kw'], { borderDash: [2, 3], pointRadius: 3 }),
          this.line('Persistence', t.map((x) => x.persistence_kw), MUTED, { borderDash: [5, 4] })
        ], labels, this.axes('heat load (kW)'));
        const leg = (this.trajChart.options!.plugins!.legend as Record<string, unknown>);
        leg['labels'] = { boxWidth: 12, color: INK, filter: (item: { text: string }) => item.text !== 'P10' };
      }
    });
  }

  stepIssue(delta: number): void {
    const i = this.issues.indexOf(this.issue);
    const next = this.issues[i + delta];
    if (next) {
      this.issue = next;
      this.loadTrajectory();
    }
  }

  score(h: number, k: string): number | null {
    const v = (this.s?.forecast?.by_horizon?.[String(h)] as unknown as Record<string, number> | undefined)?.[k];
    return typeof v === 'number' ? v : null;
  }

  // ---------------------------------------------------------------- formatting

  pct(v: number | null | undefined, d = 1): string {
    return v === null || v === undefined || !Number.isFinite(v) ? '—' : (100 * v).toFixed(d);
  }

  num(v: number | null | undefined, d = 2): string {
    if (v === null || v === undefined || !Number.isFinite(v)) {
      return '—';
    }
    const x = Math.abs(v) < 0.5 * 10 ** -d ? 0 : v;
    return x.toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });
  }

  time(ts: string): string {
    return `${ts.slice(0, 10)} ${ts.slice(11, 16)}`;
  }
}
