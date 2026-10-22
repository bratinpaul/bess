import { CommonModule } from '@angular/common';
import { Component, OnInit, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { ChartConfiguration, ChartDataset } from 'chart.js';

import {
  LossDay,
  LossLedgerRow,
  LossNode,
  LossRun,
  LossStage,
  LossSystemSummary
} from '../../../core/models/loss-decomposition.model';
import { LossDecompositionService } from '../../../core/services/loss-decomposition.service';
import { ChartCanvasComponent } from '../../telemetry/graphs/chart-canvas.component';

/** One fixed color per stage (validated categorical slots 1-7, in stack order); text never wears these. */
const COLOR: Record<string, string> = {
  batt: '#2a78d6', dc: '#eb6834', pcs: '#1baf7a', xfmr: '#eda100', hvac: '#e87ba4', controls: '#008300', standby: '#6250d6'
};
const INK = '#52514e';
const MUTED = '#9a998f';
const GRID = '#eceef0';
const SURFACE = '#ffffff';
const CRITICAL = '#d03b3b';

const LABEL: Record<string, string> = {
  batt: 'Battery internal', dc: 'DC cabling', pcs: 'PCS conversion', xfmr: 'Transformer', aux: 'Auxiliaries',
  hvac: 'Aux – HVAC', controls: 'Aux – controls', standby: 'Standby'
};
const BENCH: { key: LossStage; label: string }[] = [
  { key: 'pcs', label: 'PCS conversion' }, { key: 'batt', label: 'Battery internal' }, { key: 'aux', label: 'Auxiliaries' },
  { key: 'xfmr', label: 'Transformer' }, { key: 'standby', label: 'Standby' }
];
const BASIS_NODE: Record<string, 'term' | 'ac' | 'poi_x' | 'poi'> = { dc: 'term', ac: 'ac', poi_excl_aux: 'poi_x', plant: 'poi' };
const BASIS_LABEL: Record<string, string> = { dc: 'battery DC', ac: 'PCS AC', poi_excl_aux: 'POI excl. aux', plant: 'plant' };

type Tab = 'overview' | 'decomposition' | 'benchmarking' | 'ledger';
type ChainKey = 'batt' | 'dc' | 'pcs' | 'xfmr' | 'aux';

interface Win {
  days: number;
  eIn: Record<LossNode, number>;
  eOut: Record<LossNode, number>;
  loss: Record<string, number>;
  exp: Record<string, number>;
  stored: number;
  closure: number;
  throughput: number;
  lossUsd: number;
  excessUsd: number;
  excessKwh: number;
  fixed: number;
  variable: number;
  hasCycle: boolean;
  rte: Partial<Record<'term' | 'dc' | 'ac' | 'poi_x' | 'poi', number>>;
  factors: Partial<Record<ChainKey, number>>;
  factorsExp: Partial<Record<ChainKey, number>>;
  shares: Record<string, number>;
  rteExp: number | null;
  pr: number | null;
  basisRte: number | null;
  gapPts: number | null;
  utilization: number | null;
}

/** Insights -> Efficiency & performance -> Loss Decomposition: where the round trip goes (loss chain, waterfall, factor
 *  chain), fixed vs variable loss, loss vs loading, and the benchmark (expected vs actual, control charts, normalized
 *  efficiency, performance ratio, guarantee) - for one battery system of a loss run and a day range. */
@Component({
  selector: 'app-loss-decomposition',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink, ChartCanvasComponent],
  templateUrl: './loss-decomposition.component.html',
  styleUrl: './loss-decomposition.component.scss'
})
export class LossDecompositionComponent implements OnInit {
  private service = inject(LossDecompositionService);
  private route = inject(ActivatedRoute);

  runs: LossRun[] = [];
  runId: number | null = null;
  run: LossRun | null = null;
  systemId: number | null = null;
  allDays: LossDay[] = [];
  dayFrom = '';
  dayTo = '';
  tab: Tab = 'overview';
  error: string | null = null;
  loading = false;
  showWarnings = false;

  win: Win | null = null;
  benchStage: LossStage = 'pcs';
  loadingStage: 'pcs' | 'batt' | 'aux' | 'xfmr' = 'pcs';
  ledgerDay = '';
  ledger: LossLedgerRow[] = [];
  ledgerLoading = false;

  waterfallChart: ChartConfiguration | null = null;
  sharesChart: ChartConfiguration | null = null;
  dailyLossChart: ChartConfiguration | null = null;
  dailyRteChart: ChartConfiguration | null = null;
  fixedVarChart: ChartConfiguration | null = null;
  utilChart: ChartConfiguration | null = null;
  loadingChart: ChartConfiguration | null = null;
  benchChart: ChartConfiguration | null = null;
  controlChart: ChartConfiguration | null = null;
  cusumChart: ChartConfiguration | null = null;
  normChart: ChartConfiguration | null = null;
  prChart: ChartConfiguration | null = null;
  guaranteeChart: ChartConfiguration | null = null;
  ledgerLossChart: ChartConfiguration | null = null;
  ledgerPowerChart: ChartConfiguration | null = null;

  readonly bench = BENCH;
  readonly label = LABEL;
  readonly color = COLOR;
  readonly Math = Math;

  ngOnInit(): void {
    const qp = this.route.snapshot.queryParamMap;
    const wanted = Number(qp.get('run')) || null;
    const sys = Number(qp.get('system')) || null;
    this.service.runs().subscribe({
      next: (r) => {
        this.runs = r.filter((x) => x.status === 'COMPLETED');
        const pick = this.runs.find((x) => x.run_id === wanted) ?? this.runs[0];
        if (pick) {
          this.selectRun(pick.run_id, sys);
        }
      },
      error: () => (this.error = 'Could not reach the ML service (port 8100).')
    });
  }

  runLabel(r: LossRun): string {
    return `#${r.run_id} ${r.run_name || 'Loss run'} · ${r.date_from} → ${r.date_to} · ${r.system_ids.length} system(s)`;
  }

  selectRun(id: number, systemId: number | null = null): void {
    this.runId = id;
    this.loading = true;
    this.service.run(id).subscribe({
      next: (r) => {
        this.run = r;
        this.loading = false;
        this.systemId = systemId && r.system_ids.includes(systemId) ? systemId : r.system_ids[0] ?? null;
        this.loadDays();
      },
      error: () => {
        this.loading = false;
        this.error = `Run #${id} could not be loaded.`;
      }
    });
  }

  get systems(): { id: number; name: string }[] {
    return (this.run?.system_ids ?? []).map((id) => ({ id, name: this.run?.summary?.systems?.[String(id)]?.system_name ?? `#${id}` }));
  }

  get summary(): LossSystemSummary | null {
    return this.systemId !== null ? this.run?.summary?.systems?.[String(this.systemId)] ?? null : null;
  }

  get warnings(): string[] {
    const name = this.summary?.system_name;
    return (this.run?.warnings ?? []).filter((w) => !name || w.startsWith(name));
  }

  loadDays(): void {
    if (!this.runId || this.systemId === null) {
      return;
    }
    this.service.days(this.runId, this.systemId).subscribe({
      next: (d) => {
        this.allDays = d;
        this.dayFrom = d[0]?.day ?? '';
        this.dayTo = d[d.length - 1]?.day ?? '';
        this.ledgerDay = (d.find((x) => x.extra?.has_cycle) ?? d[0])?.day ?? '';
        this.ledger = [];
        this.rebuild();
        if (this.tab === 'ledger') {
          this.loadLedger();
        }
      },
      error: () => (this.allDays = [])
    });
  }

  setTab(t: Tab): void {
    this.tab = t;
    if (t === 'ledger' && !this.ledger.length) {
      this.loadLedger();
    }
  }

  get days(): LossDay[] {
    return this.allDays.filter((d) => d.day >= this.dayFrom && d.day <= this.dayTo);
  }

  rebuild(): void {
    const days = this.days;
    this.win = days.length ? this.windowOf(days) : null;
    this.buildOverview();
    this.buildDecomposition();
    this.buildBenchmark();
  }

  // ---------------------------------------------------------------- window maths (same formulas as the scorecard)

  private windowOf(days: LossDay[]): Win {
    const nodes: LossNode[] = ['chem', 'term', 'dc', 'ac', 'poi_x', 'poi'];
    const eIn = Object.fromEntries(nodes.map((n) => [n, 0])) as Record<LossNode, number>;
    const eOut = { ...eIn };
    const loss: Record<string, number> = { batt: 0, dc: 0, pcs: 0, xfmr: 0, hvac: 0, controls: 0, standby: 0, aux: 0 };
    const exp: Record<string, number> = { batt: 0, pcs: 0, xfmr: 0, aux: 0, standby: 0 };
    let stored = 0, closure = 0, throughput = 0, lossUsd = 0, excessUsd = 0, fixed = 0, variable = 0, hours = 0;
    const excessKwhByStage: Record<string, number> = {};
    for (const d of days) {
      for (const n of nodes) {
        eIn[n] += d.extra?.e_in?.[n] ?? 0;
        eOut[n] += d.extra?.e_out?.[n] ?? 0;
      }
      loss['batt'] += d.loss_batt_kwh; loss['dc'] += d.loss_dc_kwh; loss['pcs'] += d.loss_pcs_kwh; loss['xfmr'] += d.loss_xfmr_kwh;
      loss['hvac'] += d.aux_hvac_kwh; loss['controls'] += d.aux_ctrl_kwh; loss['standby'] += d.standby_kwh;
      exp['batt'] += d.exp_batt_kwh; exp['pcs'] += d.exp_pcs_kwh; exp['xfmr'] += d.exp_xfmr_kwh; exp['aux'] += d.exp_aux_kwh;
      exp['standby'] += d.exp_standby_kwh;
      stored += d.stored_kwh; closure += d.closure_kwh; throughput += d.throughput_kwh; lossUsd += d.loss_usd;
      fixed += d.fixed_kwh; variable += d.variable_kwh; hours += d.intervals * (this.stepMin / 60);
      for (const [k, v] of Object.entries(d.extra?.excess_usd_by_stage ?? {})) {
        excessKwhByStage[k] = (excessKwhByStage[k] ?? 0) + (v ?? 0);
      }
    }
    loss['aux'] = loss['hvac'] + loss['controls'];
    excessUsd = Object.values(excessKwhByStage).reduce((a, v) => a + Math.max(v, 0), 0);
    const excessKwh = ['batt', 'pcs', 'xfmr', 'aux', 'standby'].reduce((a, k) => a + Math.max(loss[k] - exp[k], 0), 0);
    const usable = this.summary?.usable_kwh ?? 0;
    const minFrac = this.run?.params?.min_cycle_frac ?? 0.05;
    const ok = usable > 0 && eIn.chem >= minFrac * usable && eOut.chem >= minFrac * usable;
    const rte: Win['rte'] = {};
    if (ok) {
      for (const k of ['term', 'dc', 'ac', 'poi_x', 'poi'] as const) {
        const r = eOut.chem ? eOut[k] / eOut.chem : 0;
        rte[k] = eIn[k] ? (eOut[k] + stored * r) / eIn[k] : undefined;
      }
    }
    const hasCycle = ok && Object.values(rte).every((v) => typeof v === 'number' && v > 0) && Object.keys(rte).length === 5;
    const w: Win = {
      days: days.length, eIn, eOut, loss, exp, stored, closure, throughput, lossUsd, excessUsd, excessKwh, fixed, variable, hasCycle,
      rte, factors: {}, factorsExp: {}, shares: {}, rteExp: null, pr: null, basisRte: null, gapPts: null,
      utilization: this.summary?.rated_kw && hours ? (100 * throughput / 2) / (this.summary.rated_kw * hours) : null
    };
    if (!hasCycle) {
      return w;
    }
    const r = rte as Required<Win['rte']>;
    const f: Record<ChainKey, number> = { batt: r.term, dc: r.dc / r.term, pcs: r.ac / r.dc, xfmr: r.poi_x / r.ac, aux: r.poi / r.poi_x };
    w.factors = f;
    const gap = 1 - r.poi;
    const lnTotal = Math.log(r.poi);
    if (Math.abs(lnTotal) > 1e-12) {
      const s: Record<string, number> = {};
      for (const k of Object.keys(f) as ChainKey[]) {
        s[k] = gap * Math.log(f[k]) / lnTotal;
      }
      const bTot = Math.max(loss['batt'], 0) + Math.max(loss['standby'], 0);
      const b = s['batt'];
      s['batt'] = bTot ? b * Math.max(loss['batt'], 0) / bTot : b;
      s['standby'] = bTot ? b * Math.max(loss['standby'], 0) / bTot : 0;
      const aTot = Math.max(loss['hvac'], 0) + Math.max(loss['controls'], 0);
      s['hvac'] = aTot ? s['aux'] * Math.max(loss['hvac'], 0) / aTot : s['aux'];
      s['controls'] = aTot ? s['aux'] * Math.max(loss['controls'], 0) / aTot : 0;
      w.shares = s;
    }
    const t: Record<ChainKey, number> = { batt: eIn.term + eOut.term, dc: eIn.dc + eOut.dc, pcs: throughput, xfmr: eIn.poi_x + eOut.poi_x, aux: eIn.poi_x + eOut.poi_x };
    const lAct: Record<ChainKey, number> = { batt: loss['batt'] + loss['standby'], dc: loss['dc'], pcs: loss['pcs'], xfmr: loss['xfmr'], aux: loss['aux'] };
    const lExp: Record<ChainKey, number> = { batt: exp['batt'] + exp['standby'], dc: loss['dc'], pcs: exp['pcs'], xfmr: exp['xfmr'], aux: exp['aux'] };
    const fe: Record<ChainKey, number> = { ...f };
    for (const k of Object.keys(f) as ChainKey[]) {
      if (t[k] > 0 && 1 - lAct[k] / t[k] > 0) {
        fe[k] = f[k] * (1 - lExp[k] / t[k]) / (1 - lAct[k] / t[k]);
      }
    }
    w.factorsExp = fe;
    w.rteExp = Object.values(fe).reduce((a, v) => a * v, 1);
    w.pr = w.rteExp ? r.poi / w.rteExp : null;
    const basis = this.summary?.guarantee_basis ?? 'poi_excl_aux';
    w.basisRte = r[BASIS_NODE[basis] ?? 'poi_x'] ?? null;
    w.gapPts = w.basisRte !== null && this.summary ? 100 * (this.summary.guarantee_rte - w.basisRte) : null;
    return w;
  }

  get stepMin(): number {
    const v = this.summary?.audit?.['step_min'];
    return typeof v === 'number' && v > 0 ? v : 5;
  }

  get chain(): { key: ChainKey; label: string; act: number | null; exp: number | null; pts: number | null }[] {
    const w = this.win;
    const labels: Record<ChainKey, string> = { batt: 'η battery (internal + standby)', dc: 'η DC cabling', pcs: 'η PCS (round trip)', xfmr: 'η transformer', aux: 'η auxiliaries (1 − aux fraction)' };
    return (['batt', 'dc', 'pcs', 'xfmr', 'aux'] as ChainKey[]).map((k) => ({
      key: k, label: labels[k], act: w?.factors[k] ?? null, exp: w?.factorsExp[k] ?? null,
      pts: w?.shares ? (k === 'batt' ? (w.shares['batt'] ?? 0) + (w.shares['standby'] ?? 0) : k === 'aux' ? (w.shares['hvac'] ?? 0) + (w.shares['controls'] ?? 0) : w.shares[k] ?? null) : null
    }));
  }

  get statement(): string | null {
    const w = this.win;
    if (!w?.hasCycle) {
      return null;
    }
    const r = w.rte as Required<Win['rte']>;
    const pts = (k: string) => 100 * (w.shares[k] ?? 0);
    const order = ['hvac', 'controls', 'pcs', 'batt', 'xfmr', 'standby', 'dc'].map((k) => ({ k, v: pts(k) })).filter((x) => Math.abs(x.v) >= 0.005)
      .sort((a, b) => b.v - a.v).map((x) => `${LABEL[x.k].toLowerCase()} ${x.v.toFixed(2)}`).join(', ');
    return `Plant round trip ${(100 * r.poi).toFixed(1)} % over ${w.days} day(s): the ${(100 * (1 - r.poi)).toFixed(1)} pts lost split into ${order} pts. `
      + `From the battery terminals (${(100 * r.term).toFixed(1)} %) to the plant the round trip loses ${(100 * (r.term - r.poi)).toFixed(1)} pts - `
      + `PCS ${pts('pcs').toFixed(2)}, transformer ${pts('xfmr').toFixed(2)}, auxiliaries ${(pts('hvac') + pts('controls')).toFixed(2)}`
      + (w.pr ? `. Performance ratio ${(100 * w.pr).toFixed(1)} % of the benchmark.` : '.');
  }

  basisLabel(): string {
    return BASIS_LABEL[this.summary?.guarantee_basis ?? ''] ?? '';
  }

  // ---------------------------------------------------------------- chart helpers

  private axes(y: string, extra: Record<string, unknown> = {}, x: Record<string, unknown> = {}) {
    return {
      x: { grid: { display: false }, ticks: { color: MUTED, maxRotation: 0, autoSkipPadding: 12 }, ...x },
      y: { grid: { color: GRID }, border: { display: false }, ticks: { color: MUTED }, title: { display: true, text: y, color: MUTED }, ...extra }
    };
  }

  private cfg(type: 'bar' | 'line' | 'scatter', datasets: ChartDataset[], labels: string[] | undefined, scales: unknown, legend = true,
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

  private bar(label: string, data: (number | null)[], color: string, extra: Record<string, unknown> = {}): ChartDataset {
    return { type: 'bar', label, data, backgroundColor: color, borderColor: SURFACE, borderWidth: { top: 2, bottom: 0, left: 0, right: 0 },
      borderSkipped: false, borderRadius: 2, maxBarThickness: 22, categoryPercentage: 0.85, barPercentage: 0.95, ...extra } as ChartDataset;
  }

  private dayLabels(): string[] {
    return this.days.map((d) => d.day.slice(5));
  }

  // ---------------------------------------------------------------- overview

  private buildOverview(): void {
    const w = this.win;
    if (!w) {
      this.waterfallChart = this.sharesChart = null;
      return;
    }
    // waterfall at the POI: energy in -> each stage's loss -> energy left in the cells -> energy out (exact)
    const steps: { label: string; v: number; color: string }[] = [
      { label: 'Aux – HVAC', v: w.loss['hvac'], color: COLOR['hvac'] },
      { label: 'Aux – controls', v: w.loss['controls'], color: COLOR['controls'] },
      { label: 'Transformer', v: w.loss['xfmr'], color: COLOR['xfmr'] },
      { label: 'PCS', v: w.loss['pcs'], color: COLOR['pcs'] },
      { label: 'DC cabling', v: w.loss['dc'], color: COLOR['dc'] },
      { label: 'Battery internal', v: w.loss['batt'], color: COLOR['batt'] },
      { label: 'Standby', v: w.loss['standby'], color: COLOR['standby'] },
      { label: w.stored >= 0 ? 'Left in cells' : 'Taken from cells', v: w.stored, color: '#c9c8c1' }
    ];
    const labels = ['Energy in (POI)', ...steps.map((s) => s.label), 'Energy out (POI)'];
    const data: [number, number][] = [[0, w.eIn.poi]];
    const colors = [INK];
    let level = w.eIn.poi;
    for (const s of steps) {
      data.push([level, level - s.v]);
      colors.push(s.color);
      level -= s.v;
    }
    data.push([0, w.eOut.poi]);
    colors.push(INK);
    const mwh = (v: number) => `${(v / 1000).toLocaleString(undefined, { maximumFractionDigits: 2 })} MWh`;
    this.waterfallChart = this.cfg('bar', [{ type: 'bar', label: 'kWh', data, backgroundColor: colors, borderRadius: 2, maxBarThickness: 48 } as unknown as ChartDataset],
      labels, this.axes('kWh', {}, { ticks: { color: MUTED, autoSkip: false, maxRotation: 40, minRotation: 0 } }), false,
      { mode: 'nearest', intersect: true, callbacks: { label: (ctx: { raw: unknown; dataIndex: number }) => {
        const r = ctx.raw as [number, number];
        const v = ctx.dataIndex === 0 || ctx.dataIndex === labels.length - 1 ? r[1] - r[0] : r[0] - r[1];
        const pct = w.eIn.poi ? ` · ${(100 * v / w.eIn.poi).toFixed(2)} % of the input` : '';
        return ` ${mwh(Math.abs(v))}${ctx.dataIndex > 0 && ctx.dataIndex < labels.length - 1 ? ' lost' : ''}${pct}`;
      } } });
    (this.waterfallChart.options as { interaction: unknown }).interaction = { mode: 'nearest', intersect: true };

    if (w.hasCycle) {
      const keys = ['hvac', 'controls', 'pcs', 'batt', 'xfmr', 'standby', 'dc'];
      this.sharesChart = this.cfg('bar', [{
        type: 'bar', label: 'RTE points lost', data: keys.map((k) => 100 * (w.shares[k] ?? 0)), backgroundColor: keys.map((k) => COLOR[k]),
        borderRadius: 2, maxBarThickness: 20
      } as unknown as ChartDataset], keys.map((k) => LABEL[k]), this.axes('', {}, {}), false,
      { callbacks: { label: (ctx: { raw: unknown }) => ` ${(ctx.raw as number).toFixed(3)} pts of the round trip` } });
      const o = this.sharesChart.options as Record<string, unknown>;
      o['indexAxis'] = 'y';
      o['scales'] = {
        x: { grace: '12%', grid: { color: GRID }, border: { display: false }, ticks: { color: MUTED }, title: { display: true, text: 'round-trip points lost', color: MUTED } },
        y: { grid: { display: false }, ticks: { color: INK } }
      };
      (o['plugins'] as Record<string, unknown>)['valueLabels'] = { format: (v: number) => this.num(v, 2) };
    } else {
      this.sharesChart = null;
    }
  }

  // ---------------------------------------------------------------- decomposition

  private buildDecomposition(): void {
    const days = this.days;
    if (!days.length) {
      this.dailyLossChart = this.dailyRteChart = this.fixedVarChart = this.utilChart = this.loadingChart = null;
      return;
    }
    const labels = this.dayLabels();
    const stack = (k: string, v: (d: LossDay) => number) => this.bar(LABEL[k], days.map(v), COLOR[k], { stack: 'loss' });
    this.dailyLossChart = this.cfg('bar', [
      stack('batt', (d) => d.loss_batt_kwh), stack('dc', (d) => d.loss_dc_kwh), stack('pcs', (d) => d.loss_pcs_kwh),
      stack('xfmr', (d) => d.loss_xfmr_kwh), stack('hvac', (d) => d.aux_hvac_kwh), stack('controls', (d) => d.aux_ctrl_kwh),
      stack('standby', (d) => d.standby_kwh)
    ], labels, { ...this.axes('kWh / day'), x: { stacked: true, grid: { display: false }, ticks: { color: MUTED, autoSkipPadding: 12, maxRotation: 0 } }, y: { ...this.axes('kWh / day').y, stacked: true } });

    const pct = (v: number | null) => (v === null ? null : 100 * v);
    this.dailyRteChart = this.cfg('line', [
      this.line('Battery terminals', days.map((d) => pct(d.rte_term)), COLOR['batt'], { pointRadius: 2 }),
      this.line('PCS AC', days.map((d) => pct(d.rte_ac)), COLOR['pcs'], { pointRadius: 2 }),
      this.line('POI excl. aux', days.map((d) => pct(d.rte_poi_excl_aux)), COLOR['xfmr'], { pointRadius: 2 }),
      this.line('Plant (incl. aux)', days.map((d) => pct(d.rte_plant)), INK, { pointRadius: 2 })
    ], labels, this.axes('round-trip efficiency (%)'));

    this.fixedVarChart = this.cfg('bar', [
      this.bar('Fixed (load-independent)', days.map((d) => d.fixed_kwh), '#6f6e68', { stack: 'fv' }),
      this.bar('Variable (load-dependent)', days.map((d) => d.variable_kwh), '#b9b8b0', { stack: 'fv' })
    ], labels, { x: { stacked: true, grid: { display: false }, ticks: { color: MUTED, autoSkipPadding: 12, maxRotation: 0 } }, y: { ...this.axes('kWh / day').y, stacked: true } });

    const pts = days.filter((d) => d.throughput_kwh > 0 && d.utilization_pct !== null).map((d) => ({
      x: d.utilization_pct as number, y: 100 * (d.extra?.total_loss_kwh ?? 0) / d.throughput_kwh, day: d.day
    }));
    this.utilChart = this.cfg('scatter', [{
      type: 'scatter', label: 'Day', data: pts, backgroundColor: COLOR['batt'], borderColor: SURFACE, borderWidth: 2, pointRadius: 5, pointHoverRadius: 7
    } as unknown as ChartDataset], undefined, {
      x: { type: 'linear', grid: { color: GRID }, border: { display: false }, ticks: { color: MUTED }, title: { display: true, text: 'utilization (% of rated power × 24 h)', color: MUTED } },
      y: { grid: { color: GRID }, border: { display: false }, ticks: { color: MUTED }, title: { display: true, text: 'total loss (% of AC throughput)', color: MUTED } }
    }, false, { mode: 'nearest', intersect: true, callbacks: { label: (ctx: { raw: unknown }) => {
      const r = ctx.raw as { x: number; y: number; day: string };
      return ` ${r.day}: utilization ${r.x.toFixed(1)} % · loss ${r.y.toFixed(2)} % of throughput`;
    } } });
    (this.utilChart.options as { interaction: unknown }).interaction = { mode: 'nearest', intersect: true };
    this.buildLoadingChart();
  }

  buildLoadingChart(): void {
    const curve = this.summary?.loading_curve ?? [];
    if (!curve.length) {
      this.loadingChart = null;
      return;
    }
    const k = this.loadingStage;
    const c = k === 'aux' ? COLOR['hvac'] : COLOR[k];
    const labels = curve.map((b) => `${b.from_pct.toFixed(0)}–${b.to_pct.toFixed(0)} %`);
    this.loadingChart = this.cfg('line', [
      this.line(`${LABEL[k]} · actual`, curve.map((b) => b[k]), c, { pointRadius: 4 }),
      this.line(`${LABEL[k]} · expected`, curve.map((b) => b[`exp_${k}` as 'exp_pcs']), INK, { borderDash: [5, 4], pointRadius: 0 })
    ], labels, this.axes('mean loss (kW)', {}, { title: { display: true, text: 'loading (|P_ac| / rated)', color: MUTED } }));
  }

  get directionRows(): { key: string; label: string; charge: number | null; chargePct: number | null; dis: number | null; disPct: number | null; idle: number | null }[] {
    const d = this.summary?.direction ?? {};
    const get = (dir: string, k: string) => (d[dir]?.[k] as { kwh: number; pct_of_throughput: number | null } | undefined);
    return ['batt', 'dc', 'pcs', 'xfmr', 'aux', 'standby'].map((k) => ({
      key: k, label: LABEL[k], charge: get('CHARGE', k)?.kwh ?? null, chargePct: get('CHARGE', k)?.pct_of_throughput ?? null,
      dis: get('DISCHARGE', k)?.kwh ?? null, disPct: get('DISCHARGE', k)?.pct_of_throughput ?? null, idle: get('IDLE', k)?.kwh ?? null
    }));
  }

  // ---------------------------------------------------------------- benchmarking

  private actual(d: LossDay, k: LossStage): number {
    return k === 'batt' ? d.loss_batt_kwh : k === 'pcs' ? d.loss_pcs_kwh : k === 'xfmr' ? d.loss_xfmr_kwh : k === 'aux' ? d.aux_hvac_kwh + d.aux_ctrl_kwh : d.standby_kwh;
  }

  private expected(d: LossDay, k: LossStage): number {
    return k === 'batt' ? d.exp_batt_kwh : k === 'pcs' ? d.exp_pcs_kwh : k === 'xfmr' ? d.exp_xfmr_kwh : k === 'aux' ? d.exp_aux_kwh : d.exp_standby_kwh;
  }

  buildBenchmark(): void {
    const days = this.days;
    const k = this.benchStage;
    if (!days.length) {
      this.benchChart = this.controlChart = this.cusumChart = this.normChart = this.prChart = this.guaranteeChart = null;
      return;
    }
    const labels = this.dayLabels();
    const c = k === 'aux' ? COLOR['hvac'] : COLOR[k];
    this.benchChart = this.cfg('bar', [
      this.bar(`${LABEL[k]} · actual`, days.map((d) => this.actual(d, k)), c),
      this.line(`${LABEL[k]} · expected`, days.map((d) => this.expected(d, k)), INK, { borderDash: [5, 4] })
    ], labels, this.axes('kWh / day'));

    const cc = days.map((d) => d.extra?.control?.[k] ?? null);
    const alarm = cc.map((p) => (p && (p.status === 'ewma' || p.status === 'cusum' || p.status === 'both') ? p.excess_pct : null));
    this.controlChart = this.cfg('line', [
      this.line('Daily excess %', cc.map((p) => p?.excess_pct ?? null), c, { showLine: false, pointRadius: 3, pointHoverRadius: 5 }),
      this.line('EWMA', cc.map((p) => p?.ewma ?? null), INK, {}),
      this.line('Upper control limit', cc.map((p) => p?.ucl ?? null), CRITICAL, { borderDash: [5, 4], borderWidth: 1.5 }),
      this.line('Lower limit', cc.map((p) => p?.lcl ?? null), MUTED, { borderDash: [5, 4], borderWidth: 1.5 }),
      this.line('Baseline mean', cc.map((p) => p?.center ?? null), MUTED, { borderDash: [2, 3], borderWidth: 1 }),
      this.line('Alarm', alarm, CRITICAL, { showLine: false, pointRadius: 6, pointStyle: 'triangle', pointBorderColor: SURFACE, pointBorderWidth: 2 })
    ], labels, this.axes('excess over expected (%)'));

    const h = this.run?.params?.cusum_h ?? 5;
    this.cusumChart = this.cfg('line', [
      this.line('CUSUM (excess side)', cc.map((p) => p?.cusum_pos ?? null), c, { pointRadius: 2 }),
      this.line(`Decision limit h = ${h}`, cc.map((p) => (p ? h : null)), CRITICAL, { borderDash: [5, 4], borderWidth: 1.5 })
    ], labels, this.axes('cumulative sum (σ)'));

    const norm = days.map((d) => d.extra?.normalized ?? {});
    if (k === 'pcs') {
      this.normChart = this.cfg('line', [this.line('PCS η at reference load / 25 °C', norm.map((n) => n.pcs_eta_ref_pct ?? null), c, { pointRadius: 2 })],
        labels, this.axes('η at reference (%)'), false);
    } else if (k === 'batt') {
      this.normChart = this.cfg('line', [this.line('Battery pack resistance (normalized)', norm.map((n) => n.batt_r_ref_ohm ?? null), c, { pointRadius: 2 })],
        labels, this.axes('R at reference (Ω)'), false);
    } else if (k === 'aux') {
      this.normChart = this.cfg('line', [this.line('Auxiliary load at reference ambient / load', norm.map((n) => n.aux_ref_kw ?? null), c, { pointRadius: 2 })],
        labels, this.axes('aux at reference (kW)'), false);
    } else {
      this.normChart = null;
    }

    this.prChart = this.cfg('line', [
      this.line('Performance ratio', days.map((d) => (d.performance_ratio === null ? null : 100 * d.performance_ratio)), INK, { pointRadius: 2 }),
      this.line('100 % = benchmark', days.map(() => 100), MUTED, { borderDash: [5, 4], borderWidth: 1 })
    ], labels, this.axes('actual ÷ expected RTE (%)'));

    const basis = this.summary?.guarantee_basis ?? 'poi_excl_aux';
    const col = ({ dc: 'rte_term', ac: 'rte_ac', poi_excl_aux: 'rte_poi_excl_aux', plant: 'rte_plant' } as const)[basis as 'dc'] ?? 'rte_poi_excl_aux';
    const g = this.summary ? 100 * this.summary.guarantee_rte : null;
    this.guaranteeChart = this.cfg('line', [
      this.line(`RTE (${BASIS_LABEL[basis]})`, days.map((d) => (d[col] === null ? null : 100 * (d[col] as number))), COLOR['pcs'], { pointRadius: 2 }),
      this.line(`Guaranteed ${g?.toFixed(1)} %`, days.map(() => g), CRITICAL, { borderDash: [5, 4], borderWidth: 1.5 })
    ], labels, this.axes('round-trip efficiency (%)'));
  }

  status(d: LossDay, k: LossStage): string {
    return d.extra?.control?.[k]?.status ?? '';
  }

  get alarmDays(): number {
    return this.days.filter((d) => BENCH.some((b) => ['ewma', 'cusum', 'both'].includes(this.status(d, b.key)))).length;
  }

  get fleet() {
    return this.run?.summary?.fleet ?? [];
  }

  pickSystem(id: number): void {
    this.systemId = id;
    this.loadDays();
  }

  // ---------------------------------------------------------------- ledger

  loadLedger(): void {
    if (!this.runId || this.systemId === null || !this.ledgerDay) {
      return;
    }
    this.ledgerLoading = true;
    this.service.ledger(this.runId, this.systemId, this.ledgerDay).subscribe({
      next: (rows) => {
        this.ledger = rows;
        this.ledgerLoading = false;
        this.buildLedger();
      },
      error: () => {
        this.ledger = [];
        this.ledgerLoading = false;
      }
    });
  }

  stepLedger(delta: number): void {
    const i = this.allDays.findIndex((d) => d.day === this.ledgerDay);
    const next = this.allDays[i + delta];
    if (next) {
      this.ledgerDay = next.day;
      this.loadLedger();
    }
  }

  private buildLedger(): void {
    const rows = this.ledger;
    if (!rows.length) {
      this.ledgerLossChart = this.ledgerPowerChart = null;
      return;
    }
    const perH = 60 / this.stepMin;
    const labels = rows.map((r) => r.ts.slice(11, 16));
    const kw = (v: number | null) => (v === null ? null : v * perH);
    const stack = (k: string, f: (r: LossLedgerRow) => number | null) =>
      this.bar(LABEL[k], rows.map((r) => kw(f(r))), COLOR[k], { stack: 'l', maxBarThickness: 8, categoryPercentage: 1, barPercentage: 0.9, borderWidth: 0, borderRadius: 0 });
    this.ledgerLossChart = this.cfg('bar', [
      stack('batt', (r) => r.loss_batt_kwh), stack('dc', (r) => r.loss_dc_kwh), stack('pcs', (r) => r.loss_pcs_kwh),
      stack('xfmr', (r) => r.loss_xfmr_kwh), stack('hvac', (r) => r.aux_hvac_kwh), stack('controls', (r) => r.aux_ctrl_kwh),
      stack('standby', (r) => r.standby_kwh)
    ], labels, { x: { stacked: true, grid: { display: false }, ticks: { color: MUTED, autoSkipPadding: 16, maxRotation: 0 } }, y: { ...this.axes('loss (kW)').y, stacked: true } });
    this.ledgerPowerChart = this.cfg('line', [
      this.line('POI', rows.map((r) => r.p_poi_kw), INK),
      this.line('PCS AC', rows.map((r) => r.p_ac_kw), COLOR['pcs']),
      this.line('Battery terminals', rows.map((r) => r.p_term_kw), COLOR['batt']),
      this.line('Chemistry (OCV × I)', rows.map((r) => r.p_chem_kw), COLOR['standby'], { borderDash: [4, 3] })
    ], labels, this.axes('power (kW, + charge / − discharge)'));
  }

  ledgerTotal(k: keyof LossLedgerRow): number {
    return this.ledger.reduce((a, r) => a + (Number(r[k]) || 0), 0);
  }

  // ---------------------------------------------------------------- formatting

  pct(v: number | null | undefined, d = 2): string {
    return v === null || v === undefined || !Number.isFinite(v) ? '—' : (100 * v).toFixed(d);
  }

  num(v: number | null | undefined, d = 2): string {
    if (v === null || v === undefined || !Number.isFinite(v)) {
      return '—';
    }
    const x = Math.abs(v) < 0.5 * 10 ** -d ? 0 : v; // no "-0"
    return x.toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });
  }

  signed(v: number | null | undefined, d = 2): string {
    return v === null || v === undefined || !Number.isFinite(v) ? '—' : `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v).toFixed(d)}`;
  }
}
