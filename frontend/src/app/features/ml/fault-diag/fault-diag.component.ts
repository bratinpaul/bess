import { CommonModule } from '@angular/common';
import { Component, OnInit, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { ChartConfiguration, ChartDataset } from 'chart.js';

import { AuthService } from '../../../core/auth/auth.service';

import {
  FdCandidate, FdCard, FdCause, FdClass, FdCompare, FdEffect, FdExample, FdExampleDetail, FdFishbone, FdOverview, FdPareto,
  FdRun, FdScanPoint, FdTop
} from '../../../core/models/fault-diag.model';
import { FaultDiagService, FdFilter } from '../../../core/services/fault-diag.service';
import { ChartCanvasComponent } from '../../telemetry/graphs/chart-canvas.component';

const INK = '#52514e';
const MUTED = '#9a998f';
const GRID = '#eceef0';
const CRITICAL = '#d03b3b';
const ACCENT = '#2a78d6';
const REST = '#c3c8ce';
const SUB_COLOR: Record<string, string> = { BMS: '#2a78d6', PCS: '#eb6834', HVAC: '#1baf7a', EMS: '#6250d6', PLANT: '#9a998f' };
const MODEL_COLOR = { engine: '#eda100', ml: '#2a78d6', fused: '#1baf7a' };

type Tab = 'pareto' | 'fishbone' | 'diagnosis' | 'performance';

interface BoneDraw {
  bone: string;
  hint: string;
  episodes: number;
  x0: number;
  y0: number;
  x1: number;
  y1: number;
  top: boolean;
  causes: { x: number; y: number; text: string; full: string; n: number; sources: string[]; i: number }[];
  more: number;
}

/** Insights -> Anomaly & fault detection -> Fault Diagnosis: Pareto of the fault burden, an Ishikawa (fishbone) root-cause
 *  view per fault / subsystem, the model's diagnosis of every episode (ranked candidates with signature evidence and
 *  feature contributions), scan candidates with operator review, and the classifier's confusion / per-class scores. */
@Component({
  selector: 'app-fault-diag',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink, ChartCanvasComponent],
  templateUrl: './fault-diag.component.html',
  styleUrl: './fault-diag.component.scss'
})
export class FaultDiagComponent implements OnInit {
  private service = inject(FaultDiagService);
  readonly auth = inject(AuthService);
  private route = inject(ActivatedRoute);

  tab: Tab = 'pareto';
  error: string | null = null;
  runs: FdRun[] = [];
  runId: number | null = null;
  run: FdRun | null = null;
  classes: FdClass[] = [];
  systems: { system_id: number; system_name: string }[] = [];
  filter: FdFilter = { date_from: null, date_to: null, system_id: null };

  // pareto
  overview: FdOverview | null = null;
  pareto: FdPareto | null = null;
  measure = 'count';
  groupBy = 'fault';
  cutoff = 0.8;
  paretoChart: ChartConfiguration | null = null;
  dailyChart: ChartConfiguration | null = null;

  // fishbone
  effects: FdEffect[] = [];
  effect = 'ALL';
  fish: FdFishbone | null = null;
  bones: BoneDraw[] = [];
  focusBone: string | null = null;
  readonly fishW = 1240;
  readonly fishH = 560;

  // diagnosis
  examples: FdExample[] = [];
  exFilter: 'all' | 'wrong' | 'episode' | 'none' = 'all';
  exKey: string | null = null;
  detail: FdExampleDetail | null = null;
  scans: { system_id: number; system_name: string; date_from: string; date_to: string; windows: number }[] = [];
  scanSystem: number | null = null;
  candidates: FdCandidate[] = [];
  candFilter: 'all' | 'NEW' | 'CONFIRMED' | 'REJECTED' = 'all';
  timelineChart: ChartConfiguration | null = null;
  scanDay = { from: '', to: '' };
  correct: Record<number, string> = {};
  openCand: number | null = null;

  // performance
  compare: FdCompare | null = null;
  perfModel: 'fused' | 'ml' | 'engine' = 'fused';
  recallChart: ChartConfiguration | null = null;

  readonly Math = Math;

  ngOnInit(): void {
    const q = this.route.snapshot.queryParamMap;
    const wanted = Number(q.get('run')) || null;
    const t = q.get('tab') as Tab | null;
    if (t && ['pareto', 'fishbone', 'diagnosis', 'performance'].includes(t)) {
      this.tab = t;
    }
    this.service.options().subscribe({
      next: (o) => {
        this.classes = o.classes;
        this.systems = o.systems.map((s) => ({ system_id: s.system_id, system_name: s.system_name }));
        this.filter.date_from = o.episodes.date_from;
        this.filter.date_to = o.episodes.date_to;
        this.loadAnalytics();
      },
      error: () => (this.error = 'Could not reach the ML service (port 8100).')
    });
    this.service.effects().subscribe({ next: (e) => (this.effects = e) });
    this.service.runs().subscribe({
      next: (r) => {
        this.runs = r.filter((x) => x.status === 'COMPLETED');
        const pick = this.runs.find((x) => x.run_id === wanted) ?? this.runs.find((x) => x.is_default) ?? this.runs[0];
        if (pick) {
          this.selectRun(pick.run_id);
        }
      }
    });
  }

  setTab(t: Tab): void {
    this.tab = t;
  }

  runLabel(r: FdRun): string {
    return `#${r.run_id}${r.is_default ? ' ★' : ''} · ${r.run_name || 'Fault classifier'} · ${r.params.leakage_mode} · F1 ${this.pct(r.macro_f1, 0)} %`;
  }

  selectRun(id: number): void {
    this.runId = id;
    this.detail = null;
    this.exKey = null;
    this.service.run(id).subscribe({
      next: (r) => {
        this.run = r;
        this.buildRecall();
        this.loadFishbone();
      }
    });
    this.service.examples(id).subscribe({ next: (x) => (this.examples = x) });
    this.service.compare(id).subscribe({ next: (c) => (this.compare = c) });
    this.service.scans(id).subscribe({
      next: (s) => {
        this.scans = s;
        this.scanSystem = s[0]?.system_id ?? null;
        if (s[0]) {
          this.scanDay = { from: s[0].date_from, to: s[0].date_to };
        }
        this.loadCandidates();
      }
    });
  }

  // ------------------------------------------------------------------------------------------- analytics
  loadAnalytics(): void {
    this.service.overview(this.filter).subscribe({ next: (o) => {
      this.overview = o;
      this.buildDaily();
    } });
    this.loadPareto();
    this.loadFishbone();
  }

  loadPareto(): void {
    this.service.pareto(this.measure, this.groupBy, this.filter, this.cutoff).subscribe({
      next: (p) => {
        this.pareto = p;
        this.buildPareto();
      }
    });
  }

  private buildPareto(): void {
    const p = this.pareto!;
    const items = p.items;
    const short = (s: string) => (s.length > 26 ? s.slice(0, 25) + '…' : s);
    const labels = items.map((i) => short(this.groupBy === 'fault' ? i.key : i.label));
    const full = items.map((i) => i.label);
    const fmt = (v: number) => (p.measure === 'count' || p.measure === 'alarms' ? String(Math.round(v)) : v.toLocaleString(undefined, { maximumFractionDigits: 0 }));
    const datasets: ChartDataset[] = [
      { type: 'bar', label: `${p.measure_label}${p.unit ? ' (' + p.unit + ')' : ''}`, data: items.map((i) => i.value), yAxisID: 'y',
        backgroundColor: items.map((i) => (i.vital_few ? (i.safety_critical ? CRITICAL : ACCENT) : REST)), borderRadius: 3, order: 2 } as ChartDataset,
      { type: 'line', label: 'Cumulative %', data: items.map((i) => i.cum_share * 100), yAxisID: 'y2', borderColor: INK, backgroundColor: INK,
        borderWidth: 2, pointRadius: 3, tension: 0, order: 1 } as ChartDataset,
      { type: 'line', label: `${Math.round(p.cutoff * 100)} % cut-off`, data: items.map(() => p.cutoff * 100), yAxisID: 'y2', borderColor: CRITICAL,
        borderDash: [6, 4], borderWidth: 1.5, pointRadius: 0, order: 0 } as ChartDataset
    ];
    this.paretoChart = {
      type: 'bar',
      data: { labels, datasets } as ChartConfiguration['data'],
      options: {
        responsive: true, maintainAspectRatio: false, animation: false, interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { position: 'bottom', labels: { boxWidth: 12, color: INK } },
          tooltip: { callbacks: { title: (it: { dataIndex: number }[]) => full[it[0]?.dataIndex ?? 0] ?? '',
            label: (c: { datasetIndex: number; parsed: { y: number } }) => c.datasetIndex === 0 ? ` ${fmt(c.parsed.y)} ${p.unit}` : ` ${c.parsed.y.toFixed(1)} %` } },
          valueLabels: { format: (v: number) => fmt(v) }
        } as never,
        scales: {
          x: { grid: { display: false }, ticks: { color: MUTED, maxRotation: 50, minRotation: 30, autoSkip: false, font: { size: 11 } } },
          y: { grid: { color: GRID }, border: { display: false }, ticks: { color: MUTED }, title: { display: true, text: `${p.measure_label}${p.unit ? ' (' + p.unit + ')' : ''}`, color: MUTED } },
          y2: { position: 'right', min: 0, max: 100, grid: { display: false }, border: { display: false }, ticks: { color: MUTED, callback: (v: number | string) => `${v} %` } }
        } as never
      }
    } as ChartConfiguration;
  }

  private buildDaily(): void {
    const d = this.overview?.daily;
    if (!d || !d.days.length) {
      this.dailyChart = null;
      return;
    }
    const datasets = Object.entries(d.series).map(([sub, v]) => ({
      type: 'bar', label: sub, data: v, backgroundColor: SUB_COLOR[sub] ?? MUTED, stack: 's', borderRadius: 2
    } as unknown as ChartDataset));
    this.dailyChart = {
      type: 'bar',
      data: { labels: d.days.map((x) => x.slice(5)), datasets } as ChartConfiguration['data'],
      options: {
        responsive: true, maintainAspectRatio: false, animation: false, interaction: { mode: 'index', intersect: false },
        plugins: { legend: { position: 'bottom', labels: { boxWidth: 12, color: INK } } },
        scales: {
          x: { stacked: true, grid: { display: false }, ticks: { color: MUTED, maxRotation: 0, autoSkipPadding: 10 } },
          y: { stacked: true, grid: { color: GRID }, border: { display: false }, ticks: { color: MUTED, precision: 0 }, title: { display: true, text: 'episodes detected', color: MUTED } }
        } as never
      }
    } as ChartConfiguration;
  }

  get vitalFew() {
    return this.pareto?.items.filter((i) => i.vital_few) ?? [];
  }

  // -------------------------------------------------------------------------------------------- fishbone
  loadFishbone(): void {
    this.service.fishbone(this.effect, this.filter, this.runId).subscribe({
      next: (f) => {
        this.fish = f;
        this.layoutFish();
      }
    });
  }

  fishFromPareto(key: string): void {
    if (this.groupBy === 'fault') {
      this.effect = key;
    } else if (this.groupBy === 'subsystem') {
      this.effect = `SUB:${key}`;
    } else {
      return;
    }
    this.tab = 'fishbone';
    this.loadFishbone();
  }

  private layoutFish(): void {
    const f = this.fish;
    if (!f) {
      this.bones = [];
      return;
    }
    const spineY = this.fishH / 2;
    const joins = [380, 680, 980];
    const run = 120;
    const order = ['Machine', 'Method', 'Material', 'Man', 'Measurement', 'Environment'];
    const maxCauses = 6;
    this.bones = order.map((name, k) => {
      const b = f.bones.find((x) => x.bone === name) ?? { bone: name, hint: '', episodes: 0, causes: [] as FdCause[] };
      const top = k < 3;
      const x1 = joins[k % 3];
      const y1 = spineY;
      const x0 = x1 - run;
      const y0 = top ? 56 : this.fishH - 56;
      const shown = b.causes.slice(0, maxCauses);
      const causes = shown.map((c, i) => {
        const t = (i + 1) / (maxCauses + 1);
        const x = x0 + (x1 - x0) * t;
        const y = y0 + (y1 - y0) * t;
        const text = c.cause.length > 36 ? c.cause.slice(0, 35) + '…' : c.cause;
        return { x, y, text, full: c.cause, n: c.episodes, sources: c.sources, i };
      });
      return { bone: name, hint: b.hint, episodes: b.episodes, x0, y0, x1, y1, top, causes, more: Math.max(0, b.causes.length - maxCauses) };
    });
  }

  boneCauses(name: string): FdCause[] {
    return this.fish?.bones.find((b) => b.bone === name)?.causes ?? [];
  }

  sourceLabel(s: string): string {
    return { confirmed: 'confirmed root cause', repair: 'serviced component', context: 'operating context', catalog: 'catalog (a-priori)', pattern: 'maintenance pattern' }[s] ?? s;
  }

  // ------------------------------------------------------------------------------------------- diagnosis
  get shownExamples(): FdExample[] {
    return this.examples.filter((e) => this.exFilter === 'all' || (this.exFilter === 'wrong' ? !e.correct : e.kind === this.exFilter));
  }

  openExample(e: FdExample): void {
    this.exKey = e.example_key;
    this.detail = null;
    this.service.example(this.runId!, e.example_key).subscribe({ next: (d) => (this.detail = d) });
  }

  get evidenceByFault(): { fault: string; rows: FdExampleDetail['detail']['evidence'] }[] {
    const d = this.detail;
    if (!d) {
      return [];
    }
    const order = d.detail.top3.map((t) => t.fault_code);
    const groups = new Map<string, FdExampleDetail['detail']['evidence']>();
    for (const e of d.detail.evidence) {
      if (!groups.has(e.fault_code)) {
        groups.set(e.fault_code, []);
      }
      groups.get(e.fault_code)!.push(e);
    }
    return [...groups.entries()]
      .sort((a, b) => (order.indexOf(a[0]) === -1 ? 9 : order.indexOf(a[0])) - (order.indexOf(b[0]) === -1 ? 9 : order.indexOf(b[0])))
      .map(([fault, rows]) => ({ fault, rows: rows.sort((x, y) => (y.match ?? 0) * y.weight - (x.match ?? 0) * x.weight) }));
  }

  get maxContribution(): number {
    return Math.max(1e-9, ...(this.detail?.detail.contributions ?? []).map((c) => Math.abs(c.contribution)));
  }

  loadCandidates(): void {
    if (!this.runId) {
      return;
    }
    this.service.candidates(this.runId, this.scanSystem).subscribe({ next: (c) => (this.candidates = c) });
    this.loadTimeline();
  }

  onScanSystem(): void {
    const s = this.scans.find((x) => x.system_id === this.scanSystem);
    if (s) {
      this.scanDay = { from: s.date_from, to: s.date_to };
    }
    this.loadCandidates();
  }

  loadTimeline(): void {
    if (!this.runId || !this.scanSystem || !this.scanDay.from) {
      this.timelineChart = null;
      return;
    }
    this.service.scanPoints(this.runId, this.scanSystem, this.scanDay.from, this.scanDay.to || this.scanDay.from).subscribe({
      next: (p) => this.buildTimeline(p)
    });
  }

  private buildTimeline(points: FdScanPoint[]): void {
    if (!points.length) {
      this.timelineChart = null;
      return;
    }
    const labels = points.map((p) => p.ts.slice(5, 16).replace('T', ' '));
    const fault = points.map((p) => +(1 - p.p_none).toFixed(3));
    const top = points.map((p) => (p.predicted !== 'F-NONE' ? p.probability : null));
    const alarm = points.map((p) => (p.alarms?.length ? 1.02 : null));
    const thr = this.run?.params.alert_threshold ?? 0.5;
    const names = points.map((p) => p.top3.map((t) => `${t.fault_code} ${(t.p * 100).toFixed(0)} %`).join(' · '));
    const al = points.map((p) => (p.alarms ?? []).join(', '));
    this.timelineChart = {
      type: 'line',
      data: {
        labels,
        datasets: [
          { label: 'P(any fault) = 1 − P(F-NONE)', data: fault, borderColor: ACCENT, backgroundColor: 'rgba(42,120,214,0.10)', fill: true, borderWidth: 1.5, pointRadius: 0, tension: 0 },
          { label: 'Top fault probability (when not F-NONE)', data: top, borderColor: CRITICAL, backgroundColor: CRITICAL, showLine: false, pointRadius: 2.5 },
          { label: 'Alarm in window', data: alarm, borderColor: INK, backgroundColor: INK, showLine: false, pointRadius: 2, pointStyle: 'rect' },
          { label: `Threshold ${thr}`, data: points.map(() => thr), borderColor: MUTED, borderDash: [5, 4], borderWidth: 1, pointRadius: 0 }
        ]
      } as ChartConfiguration['data'],
      options: {
        responsive: true, maintainAspectRatio: false, animation: false, interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { position: 'bottom', labels: { boxWidth: 12, color: INK } },
          tooltip: { callbacks: { afterTitle: (it: { dataIndex: number }[]) => names[it[0]?.dataIndex ?? 0],
            footer: (it: { dataIndex: number }[]) => (al[it[0]?.dataIndex ?? 0] ? `alarms: ${al[it[0].dataIndex]}` : '') } }
        } as never,
        scales: {
          x: { grid: { display: false }, ticks: { color: MUTED, maxRotation: 0, autoSkip: true, maxTicksLimit: 12 } },
          y: { min: 0, max: 1.05, grid: { color: GRID }, border: { display: false }, ticks: { color: MUTED }, title: { display: true, text: 'probability', color: MUTED } }
        } as never
      }
    } as ChartConfiguration;
  }

  get shownCandidates(): FdCandidate[] {
    return this.candidates.filter((c) => this.candFilter === 'all' || c.status === this.candFilter);
  }

  get candStats() {
    const c = this.candidates;
    const matched = c.filter((x) => x.episode_id);
    return {
      n: c.length, matched: matched.length, agree: matched.filter((x) => x.actual_fault_code === x.fault_code).length,
      reviewed: c.filter((x) => x.status !== 'NEW').length, critical: c.filter((x) => x.is_safety_critical).length
    };
  }

  review(c: FdCandidate, status: 'CONFIRMED' | 'REJECTED' | 'NEW'): void {
    const actual = status === 'CONFIRMED' ? this.correct[c.candidate_id] || c.fault_code : status === 'REJECTED' ? 'F-NONE' : null;
    this.service.review(c.candidate_id, status, actual).subscribe({
      next: () => {
        c.status = status;
        c.actual_fault_code = actual;
      }
    });
  }

  // ----------------------------------------------------------------------------------------- performance
  get card(): FdCard | null {
    return this.run?.metrics?.oof[this.perfModel] ?? null;
  }

  cellStyle(v: number, rowTotal: number, diag: boolean): Record<string, string> {
    if (!v) {
      return {};
    }
    const a = Math.min(1, v / Math.max(1, rowTotal));
    const base = diag ? '27, 175, 122' : '208, 59, 59';
    return { background: `rgba(${base}, ${0.15 + 0.7 * a})`, color: a > 0.55 ? '#fff' : INK };
  }

  rowTotal(row: number[]): number {
    return row.reduce((a, b) => a + b, 0);
  }

  private buildRecall(): void {
    const m = this.run?.metrics?.oof;
    if (!m) {
      this.recallChart = null;
      return;
    }
    const codes = m.fused.per_class.map((p) => p.fault_code);
    const rec = (c: FdCard) => codes.map((k) => +(100 * (c.per_class.find((p) => p.fault_code === k)?.recall ?? 0)).toFixed(1));
    this.recallChart = {
      type: 'bar',
      data: {
        labels: codes.map((c) => c.replace(/^F-/, '')),
        datasets: [
          { label: 'Signature engine', data: rec(m.engine), backgroundColor: MODEL_COLOR.engine, borderRadius: 2 },
          { label: 'ML', data: rec(m.ml), backgroundColor: MODEL_COLOR.ml, borderRadius: 2 },
          { label: 'Fused', data: rec(m.fused), backgroundColor: MODEL_COLOR.fused, borderRadius: 2 }
        ]
      } as ChartConfiguration['data'],
      options: {
        responsive: true, maintainAspectRatio: false, animation: false, interaction: { mode: 'index', intersect: false },
        plugins: { legend: { position: 'bottom', labels: { boxWidth: 12, color: INK } } },
        scales: {
          x: { grid: { display: false }, ticks: { color: MUTED, maxRotation: 50, minRotation: 40, autoSkip: false, font: { size: 10 } } },
          y: { min: 0, max: 100, grid: { color: GRID }, border: { display: false }, ticks: { color: MUTED, callback: (v: number | string) => `${v} %` }, title: { display: true, text: 'recall (out-of-fold)', color: MUTED } }
        } as never
      }
    } as ChartConfiguration;
  }

  // ---------------------------------------------------------------------------------------------- helpers
  cls(code: string): FdClass | undefined {
    return this.classes.find((c) => c.fault_code === code);
  }

  subsystemColor(sub: string): string {
    return SUB_COLOR[sub] ?? MUTED;
  }

  subColor(code: string): string {
    return SUB_COLOR[this.cls(code)?.subsystem ?? 'PLANT'] ?? MUTED;
  }

  topWidth(t: FdTop): number {
    return Math.max(2, t.p * 100);
  }

  pct(v: number | null | undefined, d = 1): string {
    return v === null || v === undefined || !Number.isFinite(v) ? '—' : (v * 100).toFixed(d);
  }

  num(v: number | null | undefined, d = 0): string {
    if (v === null || v === undefined || !Number.isFinite(v)) {
      return '—';
    }
    return v.toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });
  }
}
