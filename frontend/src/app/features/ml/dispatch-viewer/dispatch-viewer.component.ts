import { CommonModule } from '@angular/common';
import { Component, OnInit, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { ChartConfiguration, ChartDataset } from 'chart.js';

import { ArbDayItem, ArbDayView, ArbStudy } from '../../../core/models/arbitrage-optimizer.model';
import { ArbitrageOptimizerService } from '../../../core/services/arbitrage-optimizer.service';
import { ChartCanvasComponent } from '../../telemetry/graphs/chart-canvas.component';

// colour language shared with the other BESS dashboards
const C = {
  discharge: '#12a37f',
  charge: '#d64545',
  rt: '#2f6fed',
  dam: '#6b7280',
  p50: '#e8830c',
  band: 'rgba(232, 131, 12, 0.14)',
  soc: '#7c5cdb',
  socBand: 'rgba(124, 92, 219, 0.08)',
  compare: '#0e8f8f',
  tick: '#6b6f76',
  grid: '#eceef0'
};

interface CompareView {
  label: string;
  power: (number | null)[];
  soc: (number | null)[];
  cumTotal: number[];
  total: number | null;
}

/** Insights -> Optimization -> Dispatch Viewer: what the optimizer decided for a day, why (against the price signal) and
 *  what it earned - for the data pack's own runs (realized) or an optimizer study (backtest). Read-only. */
@Component({
  selector: 'app-dispatch-viewer',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink, ChartCanvasComponent],
  templateUrl: './dispatch-viewer.component.html',
  styleUrl: './dispatch-viewer.component.scss'
})
export class DispatchViewerComponent implements OnInit {
  private service = inject(ArbitrageOptimizerService);
  private route = inject(ActivatedRoute);
  private router = inject(Router);

  studies: ArbStudy[] = [];
  /** 'pack' or a study id */
  source: 'pack' | number = 'pack';
  days: ArbDayItem[] = [];
  day = '';
  /** none | oracle | pack | study:<id> */
  compare = 'oracle';

  view: ArbDayView | null = null;
  cmp: CompareView | null = null;
  loading = false;
  error: string | null = null;
  showPlan = false;

  heroChart: ChartConfiguration | null = null;
  socChart: ChartConfiguration | null = null;
  trackChart: ChartConfiguration | null = null;
  pnlChart: ChartConfiguration | null = null;
  waterfallChart: ChartConfiguration | null = null;
  forecastChart: ChartConfiguration | null = null;
  forecastStats: { mae: number | null; coverage: number | null; n: number } = { mae: null, coverage: null, n: 0 };

  ngOnInit(): void {
    const qp = this.route.snapshot.queryParamMap;
    const study = Number(qp.get('study'));
    if (study) {
      this.source = study;
      this.compare = 'oracle';
    }
    this.day = qp.get('day') ?? '';
    if (qp.get('compare')) {
      this.compare = qp.get('compare')!;
    }
    this.service.studies().subscribe({
      next: (s) => (this.studies = s.filter((x) => x.status === 'COMPLETED')),
      error: () => (this.studies = [])
    });
    this.loadDays();
  }

  get isStudy(): boolean {
    return this.source !== 'pack';
  }

  get studyId(): number | null {
    return this.source === 'pack' ? null : this.source;
  }

  studyLabel(s: ArbStudy): string {
    return `Study #${s.study_id}${s.study_name ? ' · ' + s.study_name : ''} (${s.mode}, ${s.date_from} → ${s.date_to})`;
  }

  get compareOptions(): { value: string; label: string }[] {
    const out = [{ value: 'none', label: 'No comparison' }, { value: 'oracle', label: 'Perfect-foresight oracle' }];
    if (this.isStudy) {
      out.push({ value: 'pack', label: "Data pack's realized run" });
    }
    for (const s of this.studies) {
      if (s.study_id !== this.studyId) {
        out.push({ value: `study:${s.study_id}`, label: `Study #${s.study_id}${s.study_name ? ' · ' + s.study_name : ''}` });
      }
    }
    return out;
  }

  onSourceChange(): void {
    if (!this.compareOptions.some((o) => o.value === this.compare)) {
      this.compare = 'oracle';
    }
    this.loadDays();
  }

  loadDays(): void {
    this.service.days(this.isStudy ? 'study' : 'pack', this.studyId).subscribe({
      next: (r) => {
        this.days = r.days;
        if (!this.days.some((d) => d.kpi_date === this.day)) {
          this.day = this.days[0]?.kpi_date ?? '';
        }
        this.load();
      },
      error: (err) => {
        this.days = [];
        this.error = err?.error?.detail || 'Could not reach the ML service (port 8100).';
      }
    });
  }

  step(delta: number): void {
    const i = this.days.findIndex((d) => d.kpi_date === this.day);
    const next = this.days[i + delta];
    if (next) {
      this.day = next.kpi_date;
      this.load();
    }
  }

  load(): void {
    if (!this.day) {
      return;
    }
    this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { study: this.studyId, day: this.day, compare: this.compare === 'oracle' ? null : this.compare },
      replaceUrl: true
    });
    this.loading = true;
    this.error = null;
    this.service.day(this.day, this.isStudy ? 'study' : 'pack', this.studyId).subscribe({
      next: (v) => {
        this.view = v;
        this.loading = false;
        this.loadCompare();
      },
      error: (err) => {
        this.loading = false;
        this.view = null;
        this.error = err?.error?.detail || 'Could not load the day.';
      }
    });
  }

  loadCompare(): void {
    const v = this.view;
    if (!v) {
      return;
    }
    this.cmp = null;
    if (this.compare === 'oracle') {
      const o = v.oracle;
      if (o?.intervals) {
        const byTs = new Map(o.intervals.map((x) => [x.ts, x]));
        let acc = 0;
        const cum: number[] = [];
        for (const it of v.intervals) {
          acc += byTs.get(it.ts)?.net ?? 0;
          cum.push(acc);
        }
        // AS revenue of the oracle is spread evenly over the day for the cumulative line
        const asPer = (o.as_usd ?? 0) / Math.max(1, v.intervals.length);
        this.cmp = {
          label: 'Perfect-foresight oracle',
          power: v.intervals.map((it) => byTs.get(it.ts)?.p ?? null),
          soc: v.intervals.map((it) => byTs.get(it.ts)?.soc ?? null),
          cumTotal: cum.map((c, i) => c + asPer * (i + 1)),
          total: o.total_usd ?? null
        };
      }
      this.buildCharts();
    } else if (this.compare === 'pack' || this.compare.startsWith('study:')) {
      const src = this.compare === 'pack' ? 'pack' : 'study';
      const id = src === 'study' ? Number(this.compare.split(':')[1]) : null;
      this.service.day(this.day, src, id).subscribe({
        next: (c) => {
          const byTs = new Map(c.intervals.map((x) => [x.ts, x]));
          let acc = 0;
          const cum = v.intervals.map((it) => {
            const x = byTs.get(it.ts);
            acc += (x?.net ?? 0) + (x?.as_usd ?? 0);
            return acc;
          });
          this.cmp = {
            label: src === 'pack' ? "Data pack's realized run" : `Study #${id}`,
            power: v.intervals.map((it) => byTs.get(it.ts)?.p_actual ?? null),
            soc: v.intervals.map((it) => byTs.get(it.ts)?.soc ?? null),
            cumTotal: cum,
            total: c.kpis['total_usd']
          };
          this.buildCharts();
        },
        error: () => {
          this.cmp = null;
          this.buildCharts();
        }
      });
    } else {
      this.buildCharts();
    }
  }

  k(key: string): number | null {
    const v = this.view?.kpis[key];
    return v === undefined ? null : v;
  }

  num(v: number | null | undefined, d = 2): string {
    return v === null || v === undefined || !Number.isFinite(v) ? '—' : v.toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });
  }

  time(ts: string | null | undefined): string {
    return ts ? ts.slice(11, 16) : '—';
  }

  // --- charts ----------------------------------------------------------------------------------------------------

  private axes(left: string, right?: string) {
    const scales: Record<string, unknown> = {
      x: { grid: { display: false }, ticks: { color: C.tick, maxRotation: 0, autoSkipPadding: 14 } },
      y: { position: 'left', grid: { color: C.grid }, border: { display: false }, ticks: { color: C.tick }, title: { display: true, text: left, color: C.tick } }
    };
    if (right) {
      scales['y1'] = { position: 'right', grid: { display: false }, border: { display: false }, ticks: { color: C.tick }, title: { display: true, text: right, color: C.tick } };
    }
    return scales;
  }

  private base(type: 'bar' | 'line' | 'scatter', datasets: ChartDataset[], labels: string[] | undefined, scales: unknown,
               legend = true): ChartConfiguration {
    return {
      type,
      data: { labels, datasets } as ChartConfiguration['data'],
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        interaction: { mode: 'index', intersect: false },
        plugins: { legend: { display: legend, position: 'bottom', labels: { boxWidth: 14, color: C.tick } } },
        scales: scales as never
      }
    };
  }

  private line(label: string, data: (number | null)[], color: string, extra: Record<string, unknown> = {}): ChartDataset {
    return { type: 'line', label, data, borderColor: color, backgroundColor: color, borderWidth: 2, pointRadius: 0, tension: 0, spanGaps: true, ...extra } as ChartDataset;
  }

  private buildCharts(): void {
    const v = this.view;
    if (!v) {
      return;
    }
    const it = v.intervals;
    const labels = it.map((x) => this.time(x.ts));
    const cmp = this.cmp;

    // hero: price (left) + dispatch (right)
    const power = it.map((x) => x.p_actual);
    const hero: ChartDataset[] = [
      { type: 'bar', label: 'Dispatch (actual, kW)', data: power, yAxisID: 'y1', order: 5,
        backgroundColor: power.map((p) => ((p ?? 0) >= 0 ? C.discharge : C.charge)), barPercentage: 1, categoryPercentage: 1 } as ChartDataset,
      this.line('P10', it.map((x) => x.p10), 'rgba(0,0,0,0)', { yAxisID: 'y', stepped: true, order: 2 }),
      this.line('Forecast P10–P90', it.map((x) => x.p90), 'rgba(0,0,0,0)', { yAxisID: 'y', stepped: true, fill: '-1', backgroundColor: C.band, order: 2 }),
      this.line('Forecast P50', it.map((x) => x.p50), C.p50, { yAxisID: 'y', stepped: true, order: 1 }),
      this.line('DAM price', it.map((x) => x.dam), C.dam, { yAxisID: 'y', stepped: true, borderDash: [5, 4], order: 1 }),
      this.line('RT price', it.map((x) => x.rt), C.rt, { yAxisID: 'y', order: 0 })
    ];
    if (v.source === 'pack') {
      hero.push(this.line('Scheduled (kW)', it.map((x) => x.p_sched), '#1f2937', { yAxisID: 'y1', stepped: true, borderWidth: 1.5, borderDash: [3, 3], order: 0 }));
    }
    if (cmp) {
      hero.push(this.line(`${cmp.label} (kW)`, cmp.power, C.compare, { yAxisID: 'y1', borderWidth: 1.5, borderDash: [6, 4], order: 0 }));
    }
    this.heroChart = this.base('bar', hero, labels, this.axes('Price (USD/MWh)', 'Power (kW, + discharge / − charge)'));
    // keep the legend readable: hide the helper P10 series
    (this.heroChart.options!.plugins!.legend as { labels: Record<string, unknown> }).labels['filter'] = (item: { text: string }) => item.text !== 'P10';

    // SOC
    const b = v.battery;
    const soc: ChartDataset[] = [
      this.line('SOC floor', it.map(() => b.soc_min), 'rgba(124,92,219,0.35)', { borderDash: [2, 3], borderWidth: 1 }),
      this.line('SOC band', it.map(() => b.soc_max), 'rgba(124,92,219,0.35)', { borderDash: [2, 3], borderWidth: 1, fill: '-1', backgroundColor: C.socBand }),
      this.line('Planned SOC (schedule)', it.map((x) => x.soc_plan), '#1f2937', { stepped: true, borderDash: [5, 4], borderWidth: 1.5 }),
      this.line(v.source === 'pack' ? 'Realized SOC (rebuilt from outcome energy)' : 'Executed SOC', it.map((x) => x.soc), C.soc)
    ];
    if (cmp) {
      soc.push(this.line(`${cmp.label} SOC`, cmp.soc, C.compare, { borderDash: [6, 4], borderWidth: 1.5 }));
    }
    this.socChart = this.base('line', soc, labels, this.axes('SOC (%)'));
    (this.socChart.options!.plugins!.legend as { labels: Record<string, unknown> }).labels['filter'] = (item: { text: string }) => item.text !== 'SOC floor';

    // scheduled vs actual
    this.trackChart = this.base('line', [
      this.line('Scheduled (kW)', it.map((x) => x.p_sched), '#1f2937', { stepped: true, borderWidth: 1.5 }),
      this.line('Actual (kW)', it.map((x) => x.p_actual), C.rt, { fill: '-1', backgroundColor: 'rgba(214,69,69,0.18)' })
    ], labels, this.axes('Power (kW)'));

    // cumulative P&L
    let g = 0, gd = 0, n = 0, t = 0;
    const cg: number[] = [], cgd: number[] = [], cn: number[] = [], ct: number[] = [];
    for (const x of it) {
      g += x.gross ?? 0;
      gd += (x.gross ?? 0) - (x.degr ?? 0);
      n += x.net ?? 0;
      t += (x.net ?? 0) + (x.as_usd ?? 0);
      cg.push(g);
      cgd.push(gd);
      cn.push(n);
      ct.push(t);
    }
    const pnl: ChartDataset[] = [
      this.line('Gross', cg, '#9aa1ab', { borderWidth: 1.5 }),
      this.line('After degradation', cgd, '#e8830c', { borderWidth: 1.5 }),
      this.line('Net (after grid cost)', cn, C.discharge)
    ];
    if ((this.k('as_usd') ?? 0) > 0) {
      pnl.push(this.line('Net + AS', ct, C.rt, { borderWidth: 1.5 }));
    }
    if (cmp) {
      pnl.push(this.line(`${cmp.label} (total)`, cmp.cumTotal, C.compare, { borderDash: [6, 4], borderWidth: 1.5 }));
    }
    this.pnlChart = this.base('line', pnl, labels, this.axes('USD (cumulative)'));

    // waterfall
    const gross = this.k('gross_usd') ?? 0, degr = this.k('degradation_usd') ?? 0, grid = this.k('grid_usd') ?? 0;
    const asr = this.k('as_usd') ?? 0, net = this.k('net_usd') ?? 0, total = this.k('total_usd') ?? 0;
    const wfLabels = ['Gross', '− Degr.', '− Grid', 'Net', '+ AS', 'Total'];
    const wfData: [number, number][] = [[0, gross], [gross, gross - degr], [gross - degr, net], [0, net], [net, net + asr], [0, total]];
    const wfColors = ['#2f6fed', '#e8830c', '#d64545', '#12a37f', '#7c5cdb', '#0e8f8f'];
    this.waterfallChart = this.base('bar', [{ type: 'bar', label: 'USD', data: wfData, backgroundColor: wfColors, borderRadius: 3, maxBarThickness: 46 } as unknown as ChartDataset],
      wfLabels, this.axes('USD'), false);
    // every step labelled (no auto-skip), short enough to fit
    ((this.waterfallChart.options!.scales as Record<string, { ticks: Record<string, unknown> }>)['x'].ticks)['autoSkip'] = false;
    this.waterfallChart.options!.plugins!.tooltip = {
      callbacks: { label: (ctx) => { const r = ctx.raw as [number, number]; return ` ${this.num(r[1] - r[0], 2)} USD`; } }
    };

    // forecast quality: hourly P50 vs realized RT (hour mean)
    const hours = new Map<string, { rt: number[]; p10: number | null; p50: number | null; p90: number | null }>();
    for (const x of it) {
      const h = x.ts.slice(0, 13);
      const e = hours.get(h) ?? { rt: [], p10: x.p10, p50: x.p50, p90: x.p90 };
      if (x.rt !== null) {
        e.rt.push(x.rt);
      }
      hours.set(h, e);
    }
    const pts: { x: number; y: number }[] = [];
    let err = 0, inBand = 0, cnt = 0;
    let lo = Infinity, hi = -Infinity;
    for (const e of hours.values()) {
      if (!e.rt.length || e.p50 === null) {
        continue;
      }
      const rtm = e.rt.reduce((a, c) => a + c, 0) / e.rt.length;
      pts.push({ x: rtm, y: e.p50 });
      err += Math.abs(e.p50 - rtm);
      if (e.p10 !== null && e.p90 !== null && rtm >= e.p10 && rtm <= e.p90) {
        inBand++;
      }
      cnt++;
      lo = Math.min(lo, rtm, e.p50);
      hi = Math.max(hi, rtm, e.p50);
    }
    this.forecastStats = { mae: cnt ? err / cnt : null, coverage: cnt ? (100 * inBand) / cnt : null, n: cnt };
    const fc = this.base('scatter', [
      { type: 'scatter', label: 'Hour: P50 vs realized RT', data: pts, backgroundColor: C.p50, pointRadius: 4 } as ChartDataset,
      { type: 'line', label: 'Perfect forecast', data: cnt ? [{ x: lo, y: lo }, { x: hi, y: hi }] : [], borderColor: '#9aa1ab', borderDash: [4, 4], borderWidth: 1, pointRadius: 0 } as unknown as ChartDataset
    ], undefined, {
      x: { type: 'linear', grid: { color: C.grid }, ticks: { color: C.tick }, title: { display: true, text: 'Realized RT price, hour mean (USD/MWh)', color: C.tick } },
      y: { grid: { color: C.grid }, border: { display: false }, ticks: { color: C.tick }, title: { display: true, text: 'Forecast P50 (USD/MWh)', color: C.tick } }
    });
    fc.options!.interaction = { mode: 'nearest', intersect: true };
    this.forecastChart = fc;
  }
}
