import { CommonModule } from '@angular/common';
import { Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';

import {
  PlanSource,
  SocBacktest,
  SocForecast,
  SocMethod,
  SocModelOption,
  SocUnit
} from '../../../core/models/soc-forecast.model';
import { SocForecastService } from '../../../core/services/soc-forecast.service';
import { ChartCanvasComponent } from '../../telemetry/graphs/chart-canvas.component';
import { AnyConfig, ms, plantLabel } from '../price-forecast-shared/pf-charts';
import { METHOD_COLORS, METHOD_DASH, METHOD_LABELS, METHOD_ORDER, SHORT_COLORS, planChart, socChart } from '../soc-forecast-shared/soc-charts';

type LiveMethod = 'hybrid' | 'physics' | 'hold';

interface EditBlock {
  start: string; // datetime-local value, plant time
  end: string;
  kw: number;
}

const LIVE_LABELS: Record<LiveMethod, string> = { hybrid: 'Hybrid', physics: 'Physics', hold: 'Hold SOC' };
const PLANT_OFFSET = '+05:30';

/** Insights -> Forecasting -> SOC Trajectory: where SOC is heading over the next hours (P10-P90), the energy and
 *  headroom it leaves and when it hits a limit - for the schedule, the typical day or a what-if plan. */
@Component({
  selector: 'app-soc-forecast',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink, ChartCanvasComponent],
  templateUrl: './soc-forecast.component.html',
  styleUrls: ['../soh-estimator/soh-estimator.component.scss', '../price-forecast/price-forecast.component.scss', './soc-forecast.component.scss']
})
export class SocForecastComponent implements OnInit {
  readonly liveLabels = LIVE_LABELS;
  readonly bandMethods: LiveMethod[] = ['hybrid', 'physics'];
  readonly shortColors = SHORT_COLORS;
  readonly methodLabels = METHOD_LABELS;
  readonly methodColors = METHOD_COLORS;

  models: SocModelOption[] = [];
  modelsLoaded = false;
  modelsError: string | null = null;
  modelKey = 'active';
  units: SocUnit[] = [];
  emsId: number | null = null;
  tab: 'live' | 'backtest' = 'live';

  source: PlanSource = 'scheduled';
  bandMethod: LiveMethod = 'hybrid';
  showPhysics = true;
  showHold = false;
  horizonH = 12;
  blocks: EditBlock[] = [];

  forecast: SocForecast | null = null;
  loading = false;
  error: string | null = null;
  socCfg?: AnyConfig;
  planCfg?: AnyConfig;

  origins: string[] = [];
  originIdx = 0;
  backtest: SocBacktest | null = null;
  btError: string | null = null;
  btMethod: SocMethod = 'hybrid_scheduled';
  btCompare = true;
  btCfg?: AnyConfig;
  btPlanCfg?: AnyConfig;
  btScores: { method: SocMethod; mae: number; end: number; cover: number }[] = [];

  constructor(private service: SocForecastService, private route: ActivatedRoute, private router: Router) {}

  ngOnInit(): void {
    const q = this.route.snapshot.queryParamMap;
    this.service.options().subscribe({ next: (o) => (this.units = o.units), error: () => (this.units = []) });
    this.service.models().subscribe({
      next: (models) => {
        this.models = models;
        this.modelsLoaded = true;
        const wanted = q.get('model');
        this.modelKey = wanted && models.some((m) => String(m.run_id) === wanted) ? wanted : 'active';
        const run = this.run;
        if (run) {
          const ems = Number(q.get('ems'));
          this.emsId = run.ems_ids.includes(ems) ? ems : run.ems_ids.includes(8) ? 8 : run.ems_ids[0];
          this.horizonH = run.horizon_h;
          this.load();
        }
      },
      error: (err) => {
        this.modelsLoaded = true;
        this.modelsError = err?.status === 0 ? 'Could not reach the ML service. Is it running on port 8100?' : 'Could not load the models.';
      }
    });
  }

  get run(): SocModelOption | undefined {
    return this.modelKey === 'active' ? this.models[0] : this.models.find((m) => String(m.run_id) === this.modelKey);
  }

  get unit(): SocUnit | undefined {
    return this.units.find((u) => u.ems_id === this.emsId);
  }

  optionLabel(m: SocModelOption): string {
    const best = m.best_method ? `${METHOD_LABELS[m.best_method]} MAE ${m.metrics?.[m.best_method]?.mae?.toFixed(2) ?? '—'}` : '';
    return `#${m.run_id}${m.run_name ? ' ' + m.run_name : ''}${m.is_default ? ' (default)' : ''} · ${m.ems_ids.length} EMS · ${m.horizon_h} h · ${best}`;
  }

  unitLabel(id: number): string {
    const u = this.units.find((x) => x.ems_id === id);
    return u ? `${u.site_name ?? u.system_name ?? 'EMS ' + id} · ${u.ems_code}` : `EMS ${id}`;
  }

  get horizonOptions(): number[] {
    const max = this.run?.horizon_h ?? 12;
    return [1, 2, 4, 6, 8, 12, 18, 24].filter((h) => h <= max);
  }

  selectModel(key: string): void {
    this.modelKey = key;
    const run = this.run;
    if (run && (!this.emsId || !run.ems_ids.includes(this.emsId))) {
      this.emsId = run.ems_ids[0];
    }
    this.horizonH = Math.min(this.horizonH, run?.horizon_h ?? 12);
    this.load();
  }

  selectEms(id: number): void {
    this.emsId = id;
    this.blocks = [];
    this.load();
  }

  setTab(t: 'live' | 'backtest'): void {
    this.tab = t;
    if (t === 'backtest' && !this.origins.length) {
      this.loadOrigins();
    }
  }

  private load(): void {
    this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { model: this.modelKey === 'active' ? null : this.modelKey, ems: this.emsId },
      replaceUrl: true
    });
    this.origins = [];
    this.backtest = null;
    this.loadForecast();
    if (this.tab === 'backtest') {
      this.loadOrigins();
    }
  }

  // ---------------------------------------------------------------- live

  setSource(s: PlanSource): void {
    this.source = s;
    if (s === 'custom' && !this.blocks.length && this.forecast) {
      this.seedBlocks();
    }
    this.loadForecast();
  }

  loadForecast(): void {
    if (!this.emsId) {
      return;
    }
    this.loading = true;
    this.error = null;
    const blocks =
      this.source === 'custom'
        ? this.blocks
            .filter((b) => b.start && b.end && b.end > b.start)
            .map((b) => ({ start: b.start + ':00' + PLANT_OFFSET, end: b.end + ':00' + PLANT_OFFSET, kw: Number(b.kw) || 0 }))
        : [];
    this.service.forecast(this.modelKey, this.emsId, this.source, blocks, Number(this.horizonH)).subscribe({
      next: (f) => {
        this.forecast = f;
        this.loading = false;
        if (this.source === 'custom' && !this.blocks.length) {
          this.seedBlocks();
        }
        this.buildLive();
      },
      error: (err) => {
        this.loading = false;
        this.forecast = null;
        this.error = err?.error?.detail || 'Could not forecast.';
      }
    });
  }

  /** A starting what-if: charge at half power for 2 h from the next half hour. */
  private seedBlocks(): void {
    const f = this.forecast;
    if (!f) {
      return;
    }
    const o = ms(f.origin_ts);
    const start = Math.ceil((o + 1) / (30 * 60e3)) * 30 * 60e3;
    const ratedKw = (this.unit?.rated_power_mw ?? 1) * 1000;
    this.blocks = [{ start: this.local(start), end: this.local(start + 2 * 3600e3), kw: Math.round(ratedKw * 0.5) }];
  }

  private local(t: number): string {
    return new Date(t + 330 * 60e3).toISOString().slice(0, 16);
  }

  addBlock(): void {
    const last = this.blocks[this.blocks.length - 1];
    const start = last ? ms(last.end + ':00' + PLANT_OFFSET) : ms(this.forecast?.origin_ts ?? new Date().toISOString()) + 30 * 60e3;
    this.blocks = [...this.blocks, { start: this.local(start), end: this.local(start + 3600e3), kw: 0 }];
  }

  removeBlock(i: number): void {
    this.blocks = this.blocks.filter((_, j) => j !== i);
  }

  buildLive(): void {
    const f = this.forecast;
    if (!f) {
      return;
    }
    const xs = f.times.map(ms);
    const origin = ms(f.origin_ts);
    const tr = f.trajectories;
    const bandColor = SHORT_COLORS[this.bandMethod];
    const lines = [
      {
        label: `${LIVE_LABELS[this.bandMethod]} P50`,
        color: bandColor,
        width: 2.5,
        points: [{ x: origin, y: f.soc_now }, ...tr[this.bandMethod].p50.map((y, i) => ({ x: xs[i], y }))]
      }
    ];
    for (const m of ['physics', 'hold'] as LiveMethod[]) {
      if (m !== this.bandMethod && (m === 'physics' ? this.showPhysics : this.showHold)) {
        lines.push({
          label: `${LIVE_LABELS[m]} P50`,
          color: SHORT_COLORS[m],
          width: 1.5,
          points: [{ x: origin, y: f.soc_now }, ...tr[m].p50.map((y, i) => ({ x: xs[i], y }))],
          dash: [6, 4]
        } as any);
      }
    }
    this.socCfg = socChart({
      history: f.history.map((h) => ({ x: ms(h.ts), y: h.soc })),
      band: {
        label: LIVE_LABELS[this.bandMethod],
        color: bandColor,
        points: [{ x: origin, lo: f.soc_now, hi: f.soc_now }, ...tr[this.bandMethod].p10.map((lo, i) => ({ x: xs[i], lo, hi: tr[this.bandMethod].p90[i] }))]
      },
      lines,
      originMs: origin,
      socMin: f.physics.soc_min,
      socMax: f.physics.soc_max
    });
    const hist = f.history.map((h) => ({ x: ms(h.ts), y: h.sp }));
    const planTimes = [origin, ...xs.slice(0, -1)]; // step k's setpoint applies from its start
    const plan = f.plan_kw.map((y, i) => ({ x: planTimes[i], y }));
    const allX = [...hist.map((p) => p.x), ...xs];
    this.planCfg = planChart(hist, plan, origin, this.planLabel, Math.min(...allX), Math.max(...allX));
  }

  get planLabel(): string {
    return this.source === 'scheduled' ? 'Plan · schedule' : this.source === 'typical' ? 'Plan · typical day' : 'Plan · what-if';
  }

  /** P50 / P10 / P90 at a number of hours ahead. */
  at(hours: number) {
    const f = this.forecast;
    if (!f) {
      return null;
    }
    const i = Math.min(f.times.length - 1, Math.round((hours * 60) / 5) - 1);
    const t = f.trajectories[this.bandMethod];
    return { p10: t.p10[i], p50: t.p50[i], p90: t.p90[i], ts: f.times[i] };
  }

  get endHours(): number {
    return this.forecast ? (this.forecast.times.length * 5) / 60 : 0;
  }

  num(v: number | null | undefined, d = 1): string {
    return typeof v === 'number' && Number.isFinite(v) ? v.toFixed(d) : '—';
  }

  kwh(v: number | null | undefined): string {
    return typeof v === 'number' && Number.isFinite(v) ? `${Math.round(v).toLocaleString()} kWh` : '—';
  }

  timeOf(ts: string | null | undefined): string {
    return ts ? plantLabel(ms(ts)) : 'not within the horizon';
  }

  inHours(ts: string | null | undefined): string {
    if (!ts || !this.forecast) {
      return '';
    }
    const h = (ms(ts) - ms(this.forecast.origin_ts)) / 3600e3;
    return h <= 0.09 ? '(now)' : `(in ${h < 1 ? Math.round(h * 60) + ' min' : h.toFixed(1) + ' h'})`;
  }

  get upcoming() {
    const f = this.forecast;
    if (!f) {
      return [];
    }
    const o = ms(f.origin_ts);
    return f.commands.filter((c) => ms(c.end) > o).slice(0, 12);
  }

  // ---------------------------------------------------------------- backtest

  loadOrigins(): void {
    const run = this.run;
    if (!run || !this.emsId) {
      return;
    }
    this.service.origins(run.run_id, this.emsId).subscribe({
      next: (o) => {
        this.origins = o;
        this.originIdx = Math.max(0, Math.floor(o.length / 2));
        this.loadBacktest();
      },
      error: () => (this.origins = [])
    });
  }

  stepOrigin(d: number): void {
    const i = this.originIdx + d;
    if (i >= 0 && i < this.origins.length) {
      this.originIdx = i;
      this.loadBacktest();
    }
  }

  setOrigin(i: number): void {
    this.originIdx = Number(i);
    this.loadBacktest();
  }

  originLabel(ts: string): string {
    return plantLabel(ms(ts));
  }

  loadBacktest(): void {
    const run = this.run;
    const o = this.origins[this.originIdx];
    if (!run || !this.emsId || !o) {
      return;
    }
    this.btError = null;
    this.service.backtest(run.run_id, this.emsId, o).subscribe({
      next: (b) => {
        this.backtest = b;
        this.buildBacktest();
      },
      error: (err) => (this.btError = err?.error?.detail || 'Could not load the backtest.')
    });
  }

  get btMethods(): SocMethod[] {
    return METHOD_ORDER;
  }

  buildBacktest(): void {
    const b = this.backtest;
    const f = this.forecast;
    if (!b) {
      return;
    }
    const origin = ms(b.origin_ts);
    const at = (step: number) => origin + (step + 1) * 5 * 60e3;
    const of = (m: SocMethod) => b.points.filter((p) => p.method === m);
    const sel = of(this.btMethod);
    const soc0 = b.history.length ? b.history[b.history.length - 1].soc : null;
    const lines = [
      {
        label: `${METHOD_LABELS[this.btMethod]} P50`,
        color: METHOD_COLORS[this.btMethod],
        dash: METHOD_DASH[this.btMethod],
        width: 2.5,
        points: [{ x: origin, y: soc0 }, ...sel.map((p) => ({ x: at(p.step), y: p.p50 }))]
      }
    ];
    if (this.btCompare) {
      for (const m of METHOD_ORDER.filter((x) => x !== this.btMethod)) {
        lines.push({
          label: `${METHOD_LABELS[m]} P50`,
          color: METHOD_COLORS[m],
          dash: METHOD_DASH[m],
          width: 1.3,
          points: [{ x: origin, y: soc0 }, ...of(m).map((p) => ({ x: at(p.step), y: p.p50 }))]
        });
      }
    }
    this.btCfg = socChart({
      history: b.history.map((h) => ({ x: ms(h.ts), y: h.soc })),
      actualAfter: [{ x: origin, y: soc0 }, ...sel.map((p) => ({ x: at(p.step), y: p.actual }))],
      band: {
        label: METHOD_LABELS[this.btMethod],
        color: METHOD_COLORS[this.btMethod],
        points: [{ x: origin, lo: soc0, hi: soc0 }, ...sel.map((p) => ({ x: at(p.step), lo: p.p10, hi: p.p90 }))]
      },
      lines,
      originMs: origin,
      socMin: f?.physics.soc_min ?? null,
      socMax: f?.physics.soc_max ?? null
    });
    const hist = b.history.map((h) => ({ x: ms(h.ts), y: h.sp }));
    const planM = this.btMethod.endsWith('typical') ? 'hybrid_typical' : 'hybrid_scheduled';
    const plan = of(planM).map((p) => ({ x: origin + p.step * 5 * 60e3, y: p.plan_kw }));
    const allX = [...hist.map((p) => p.x), ...plan.map((p) => p.x)];
    this.btPlanCfg = planChart(hist, plan, origin, planM.endsWith('typical') ? 'Plan · typical day' : 'Plan · schedule', Math.min(...allX), Math.max(...allX));
    this.btScores = METHOD_ORDER.map((m) => {
      const pts = of(m).filter((p) => p.actual !== null && p.p50 !== null);
      const n = Math.max(pts.length, 1);
      const last = pts[pts.length - 1];
      return {
        method: m,
        mae: pts.reduce((s, p) => s + Math.abs((p.actual ?? 0) - (p.p50 ?? 0)), 0) / n,
        end: last ? Math.abs((last.actual ?? 0) - (last.p50 ?? 0)) : NaN,
        cover: (100 * pts.filter((p) => (p.actual ?? 0) >= (p.p10 ?? 0) && (p.actual ?? 0) <= (p.p90 ?? 0)).length) / n
      };
    }).sort((a, c) => a.mae - c.mae);
  }
}
