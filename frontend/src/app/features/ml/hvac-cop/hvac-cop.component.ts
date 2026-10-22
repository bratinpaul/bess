import { CommonModule } from '@angular/common';
import { Component, OnInit, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { ChartConfiguration, ChartDataset } from 'chart.js';
import { AuthService } from '../../../core/auth/auth.service';

import { CopPoint, CopPrediction, CopRun, CopUnitSummary } from '../../../core/models/hvac-cop.model';
import { HvacCopService } from '../../../core/services/hvac-cop.service';
import { ChartCanvasComponent } from '../../telemetry/graphs/chart-canvas.component';

const WHAT_IF_TRAINERS_ONLY = 'What-if predictions are limited to model trainers (Admin, Data Scientist).';

const INK = '#52514e';
const MUTED = '#9a998f';
const GRID = '#eceef0';
const CRITICAL = '#d03b3b';
const CAT = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#6250d6'];
/** one hue, light -> dark, for the part-load ratio (a magnitude) */
const RAMP = ['#86b6ef', '#5598e7', '#2a78d6', '#184f95'];

type Tab = 'map' | 'scorecard' | 'degradation' | 'closure' | 'whatif';

/** Insights -> Efficiency & performance -> HVAC COP & Cooling: the performance map, the scorecard, the degradation monitor,
 *  the measurement closure and a what-if / setpoint view, per HVAC unit of a COP run. */
@Component({
  selector: 'app-hvac-cop',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink, ChartCanvasComponent],
  templateUrl: './hvac-cop.component.html',
  styleUrl: './hvac-cop.component.scss'
})
export class HvacCopComponent implements OnInit {
  private auth = inject(AuthService);
  private service = inject(HvacCopService);
  private route = inject(ActivatedRoute);

  runs: CopRun[] = [];
  runId: number | null = null;
  run: CopRun | null = null;
  hvacId: number | null = null;
  tab: Tab = 'map';
  error: string | null = null;
  showWarnings = false;

  day = '';
  points: CopPoint[] = [];
  whatif = { ambient: 35, supply: 25, mode: 'load' as 'load' | 'plr', load: 30, plr: 0.75 };
  prediction: CopPrediction | null = null;
  predictError: string | null = null;

  scatterChart: ChartConfiguration | null = null;
  capChart: ChartConfiguration | null = null;
  plrChart: ChartConfiguration | null = null;
  dailyCopChart: ChartConfiguration | null = null;
  kwtChart: ChartConfiguration | null = null;
  controlChart: ChartConfiguration | null = null;
  cusumChart: ChartConfiguration | null = null;
  etaChart: ChartConfiguration | null = null;
  filterChart: ChartConfiguration | null = null;
  dischargeChart: ChartConfiguration | null = null;
  closureCoolChart: ChartConfiguration | null = null;
  closureCopChart: ChartConfiguration | null = null;
  rejChart: ChartConfiguration | null = null;
  hourlyChart: ChartConfiguration | null = null;
  ambientChart: ChartConfiguration | null = null;

  readonly Math = Math;

  ngOnInit(): void {
    const wanted = Number(this.route.snapshot.queryParamMap.get('run')) || null;
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

  runLabel(r: CopRun): string {
    return `#${r.run_id} ${r.run_name || 'COP run'} · ${r.date_from} → ${r.date_to} · ${r.hvac_ids.length} unit(s)`;
  }

  selectRun(id: number): void {
    this.runId = id;
    this.service.run(id).subscribe({
      next: (r) => {
        this.run = r;
        this.hvacId = r.hvac_ids[0] ?? null;
        this.onUnit();
      },
      error: () => (this.error = `Run #${id} could not be loaded.`)
    });
  }

  get units(): { id: number; name: string }[] {
    return (this.run?.hvac_ids ?? []).map((id) => {
      const s = this.run?.summary?.units?.[String(id)];
      return { id, name: s ? `${s.hvac_code} · ${s.site_name ?? ''}` : `#${id}` };
    });
  }

  get s(): CopUnitSummary | null {
    return this.hvacId !== null ? this.run?.summary?.units?.[String(this.hvacId)] ?? null : null;
  }

  get warnings(): string[] {
    const code = this.s?.hvac_code;
    return (this.run?.warnings ?? []).filter((w) => !code || w.startsWith(code));
  }

  get days(): string[] {
    return (this.s?.daily ?? []).map((d) => d.day);
  }

  onUnit(): void {
    const s = this.s;
    if (!s) {
      return;
    }
    const busiest = [...s.daily].sort((a, b) => b.cooling_h - a.cooling_h)[0];
    this.day = busiest?.day ?? s.daily[0]?.day ?? '';
    this.whatif.supply = s.sensitivities?.at?.supply_c ? Math.round(s.sensitivities.at.supply_c) : 25;
    this.buildMap();
    this.buildScorecard();
    this.buildDegradation();
    this.buildHourly();
    this.loadDay();
    this.predict();
  }

  setTab(t: Tab): void {
    this.tab = t;
  }

  // ---------------------------------------------------------------- helpers

  private axes(y: string, x: Record<string, unknown> = {}, yx: Record<string, unknown> = {}) {
    return {
      x: { grid: { display: false }, ticks: { color: MUTED, maxRotation: 0, autoSkipPadding: 14 }, ...x },
      y: { grid: { color: GRID }, border: { display: false }, ticks: { color: MUTED }, title: { display: true, text: y, color: MUTED }, ...yx }
    };
  }

  private cfg(type: 'bar' | 'line' | 'scatter', datasets: ChartDataset[], labels: (string | number)[] | undefined, scales: unknown,
              legend = true, interaction: Record<string, unknown> = { mode: 'index', intersect: false }): ChartConfiguration {
    return {
      type,
      data: { labels, datasets } as ChartConfiguration['data'],
      options: {
        responsive: true, maintainAspectRatio: false, animation: false, interaction,
        plugins: { legend: { display: legend, position: 'bottom', labels: { boxWidth: 12, color: INK } } },
        scales: scales as never
      }
    } as ChartConfiguration;
  }

  private line(label: string, data: (number | null)[] | { x: number; y: number }[], color: string, extra: Record<string, unknown> = {}): ChartDataset {
    return { type: 'line', label, data, borderColor: color, backgroundColor: color, borderWidth: 2, pointRadius: 0, pointHoverRadius: 4,
      tension: 0, spanGaps: false, ...extra } as ChartDataset;
  }

  private linearX(title: string, extra: Record<string, unknown> = {}) {
    return { type: 'linear', grid: { color: GRID }, border: { display: false }, ticks: { color: MUTED }, title: { display: true, text: title, color: MUTED }, ...extra };
  }

  // ---------------------------------------------------------------- performance map

  private buildMap(): void {
    const s = this.s!;
    const g = s.map_grid;
    const bands: { label: string; lo: number; hi: number; c: string }[] = [
      { label: 'PLR < 50 %', lo: 0, hi: 0.5, c: CAT[0] }, { label: 'PLR 50–75 %', lo: 0.5, hi: 0.75, c: CAT[1] },
      { label: 'PLR ≥ 75 %', lo: 0.75, hi: 9, c: CAT[2] }];
    const ds: ChartDataset[] = bands.map((b) => ({
      type: 'scatter', label: `Measured · ${b.label}`, data: s.scatter.filter((p) => p.plr >= b.lo && p.plr < b.hi).map((p) => ({ x: p.amb, y: p.cop })),
      backgroundColor: b.c, borderColor: '#ffffff', borderWidth: 1, pointRadius: 3, pointHoverRadius: 5
    } as unknown as ChartDataset));
    Object.keys(g.cop).forEach((p, i) => ds.push(this.line(`Map · PLR ${Math.round(Number(p) * 100)} %`,
      g.ambient_c.map((a, j) => ({ x: a, y: g.cop[p][j] })), RAMP[i] ?? INK, { borderWidth: 2 })));
    this.scatterChart = this.cfg('scatter', ds, undefined, {
      x: this.linearX('ambient (°C)'), y: { grid: { color: GRID }, border: { display: false }, ticks: { color: MUTED }, title: { display: true, text: 'COP', color: MUTED } }
    }, true, { mode: 'nearest', intersect: false });

    this.capChart = this.cfg('line', Object.keys(g.cap).map((p, i) => this.line(`PLR ${Math.round(Number(p) * 100)} %`,
      g.ambient_c.map((a, j) => ({ x: a, y: g.cap[p][j] })), RAMP[i] ?? INK)), undefined, {
      x: this.linearX('ambient (°C)'), y: { grid: { color: GRID }, border: { display: false }, ticks: { color: MUTED }, title: { display: true, text: 'cooling capacity (kW)', color: MUTED } }
    });
    this.plrChart = this.cfg('line', [this.line('f(PLR)', g.plr_curve.plr.map((p, j) => ({ x: p * 100, y: g.plr_curve.f[j] })), CAT[0], { pointRadius: 2 })],
      undefined, { x: this.linearX('part-load ratio (% compressor speed)'), y: { grid: { color: GRID }, border: { display: false }, ticks: { color: MUTED }, title: { display: true, text: 'COP multiplier (1 = full load)', color: MUTED } } }, false);
  }

  // ---------------------------------------------------------------- scorecard

  private buildScorecard(): void {
    const d = this.s!.daily;
    const labels = d.map((x) => x.day.slice(5));
    this.dailyCopChart = this.cfg('line', [
      this.line('Weighted COP (Σ cooling / Σ power)', d.map((x) => x.weighted_cop), INK, { pointRadius: 2 }),
      this.line(`Normalized COP (at ${this.run?.params?.ref_ambient_c} °C reference)`, d.map((x) => x.cop_normalized), CAT[0], { pointRadius: 2 }),
      this.line('Mean steady COP', d.map((x) => x.cop_mean), MUTED, { borderDash: [4, 3], borderWidth: 1.5 })
    ], labels, this.axes('COP'));
    this.kwtChart = this.cfg('line', [this.line('kW/ton', d.map((x) => x.kw_per_ton), CAT[1], { pointRadius: 2 })], labels, this.axes('kW per ton of cooling'), false);
  }

  // ---------------------------------------------------------------- degradation

  private buildDegradation(): void {
    const d = this.s!.daily;
    const labels = d.map((x) => x.day.slice(5));
    const c = d.map((x) => x.control);
    const alarm = d.map((x) => (x.control && x.control.status !== 'ok' ? x.residual_mean : null));
    this.controlChart = this.cfg('line', [
      this.line('Daily mean residual (actual − expected)', d.map((x) => (x.control ? x.residual_mean : null)), CAT[0], { showLine: false, pointRadius: 3 }),
      this.line('EWMA', c.map((x) => x?.ewma ?? null), INK),
      this.line('Lower control limit', c.map((x) => x?.lcl ?? null), CRITICAL, { borderDash: [5, 4], borderWidth: 1.5 }),
      this.line('Baseline mean', c.map((x) => x?.center ?? null), MUTED, { borderDash: [2, 3], borderWidth: 1 }),
      this.line('Alarm', alarm, CRITICAL, { showLine: false, pointRadius: 6, pointStyle: 'triangle' })
    ], labels, this.axes('COP residual'));
    const h = this.run?.params?.cusum_h ?? 5;
    this.cusumChart = this.cfg('line', [
      this.line('CUSUM (COP below expected)', c.map((x) => x?.cusum_neg ?? null), CAT[0], { pointRadius: 2 }),
      this.line(`Decision limit h = ${h}`, c.map((x) => (x ? h : null)), CRITICAL, { borderDash: [5, 4], borderWidth: 1.5 })
    ], labels, this.axes('cumulative sum (σ)'));
    this.etaChart = this.cfg('line', [this.line('η 2nd law (COP ÷ Carnot)', d.map((x) => x.eta_2nd_law), CAT[2], { pointRadius: 2 })], labels, this.axes('η 2nd law'), false);
    this.filterChart = this.cfg('line', [this.line('Filter differential pressure', d.map((x) => x.filter_dp_pa), CAT[3], { pointRadius: 2 })], labels, this.axes('filter dp (Pa)'), false);
    this.dischargeChart = this.cfg('line', [this.line('Discharge pressure above its ambient-explained level', d.map((x) => x.discharge_excess_bar), CAT[4], { pointRadius: 2 })],
      labels, this.axes('excess discharge (bar)'), false);
  }

  // ---------------------------------------------------------------- closure

  loadDay(): void {
    if (!this.runId || this.hvacId === null || !this.day) {
      return;
    }
    this.service.points(this.runId, this.hvacId, this.day).subscribe({
      next: (p) => {
        this.points = p;
        this.buildClosure();
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

  private buildClosure(): void {
    const p = this.points;
    const labels = p.map((x) => x.ts.slice(11, 16));
    const cool = (x: CopPoint) => x.mode === 'COOLING';
    this.closureCoolChart = this.cfg('line', [
      this.line('Logged cooling (cooling_capacity_kw)', p.map((x) => (cool(x) ? x.cap_actual_kw : null)), INK),
      this.line('Coolant loop (flow × ρ·cp × ΔT)', p.map((x) => (cool(x) ? x.q_dt_kw : null)), CAT[1]),
      this.line('Expected capacity (map)', p.map((x) => x.cap_expected_kw), CAT[6], { borderDash: [5, 4] })
    ], labels, this.axes('cooling (kW)'));
    this.closureCopChart = this.cfg('line', [
      this.line('Logged cop', p.map((x) => (cool(x) ? x.cop_logged : null)), INK),
      this.line('Cooling ÷ power', p.map((x) => (cool(x) ? x.cop_ratio : null)), CAT[1]),
      this.line('Expected (map)', p.map((x) => x.cop_expected), CAT[6], { borderDash: [5, 4] })
    ], labels, this.axes('COP'));
    this.rejChart = this.cfg('bar', [{
      type: 'bar', label: 'heat_rejected − (cooling + power)', data: p.map((x) => (cool(x) ? x.rej_closure_kw : null)),
      backgroundColor: CAT[0], borderRadius: 1, maxBarThickness: 8, categoryPercentage: 1, barPercentage: 0.9
    } as unknown as ChartDataset], labels, this.axes('condenser balance gap (kW)'), false);
  }

  closure(k: string): number | null {
    const v = this.s?.closure?.[k];
    return typeof v === 'number' ? v : null;
  }

  // ---------------------------------------------------------------- what-if / setpoint

  private buildHourly(): void {
    const h = this.s?.sensitivities?.hourly ?? [];
    const labels = h.map((x) => `${String(x.hour).padStart(2, '0')}:00`);
    const best = new Set(this.s?.sensitivities?.best_hours ?? []);
    this.hourlyChart = this.cfg('bar', [
      { type: 'bar', label: 'Expected COP at the median load', data: h.map((x) => x.cop_expected_at_median_load),
        backgroundColor: h.map((x) => (best.has(x.hour) ? CAT[2] : '#b7d3f6')), borderRadius: 2, maxBarThickness: 18 } as unknown as ChartDataset,
      this.line('Measured steady COP', h.map((x) => x.cop_actual_mean), INK, { pointRadius: 3, showLine: false })
    ], labels, this.axes('COP', {}, { suggestedMin: Math.min(...h.map((x) => x.cop_expected_at_median_load)) - 0.3 }));
    this.ambientChart = this.cfg('line', [this.line('Mean ambient', h.map((x) => x.ambient_c), CAT[1], { pointRadius: 2 })], labels, this.axes('ambient (°C)'), false);
  }

  predict(): void {
    if (!this.runId || this.hvacId === null) {
      return;
    }
    if (this.run?.params?.lift_source === 'pressure') {
      this.predictError = 'This run took the lift from the refrigerant pressures - the what-if needs a temperature-lift run.';
      return;
    }
    this.predictError = null;
    if (!this.auth.hasPermission('ml.run:execute')) {
      this.predictError = WHAT_IF_TRAINERS_ONLY;
      return;
    }
    this.service.predict({
      run_id: this.runId, hvac_id: this.hvacId, ambient_c: Number(this.whatif.ambient), supply_c: Number(this.whatif.supply),
      plr: this.whatif.mode === 'plr' ? Number(this.whatif.plr) : null, heat_load_kw: this.whatif.mode === 'load' ? Number(this.whatif.load) : null
    }).subscribe({
      next: (p) => (this.prediction = p),
      error: (e) => (this.predictError = e?.error?.detail || 'Prediction failed.')
    });
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

  signed(v: number | null | undefined, d = 2): string {
    return v === null || v === undefined || !Number.isFinite(v) ? '—' : `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v).toFixed(d)}`;
  }
}
