import { CommonModule } from '@angular/common';
import { Component, OnInit, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { AuthService } from '../../../core/auth/auth.service';

import {
  RulBacktestPoint,
  RulForecastRow,
  RulMethod,
  RulMethodResult,
  RulModelOption,
  RulPrediction,
  RulSystem
} from '../../../core/models/rul.model';
import { RulService } from '../../../core/services/rul.service';
import { ChartCanvasComponent } from '../../telemetry/graphs/chart-canvas.component';
import { AnyConfig } from '../price-forecast-shared/pf-charts';
import {
  R_COLORS,
  R_LABELS,
  R_ORDER,
  XY,
  backtestChart,
  fleetChart,
  healthChart,
  survivalChart,
  yearOf
} from '../rul-shared/rul-charts';

const WHAT_IF_TRAINERS_ONLY = 'What-if predictions are limited to model trainers (Admin, Data Scientist).';

interface FleetRow {
  system_id: number;
  code: string;
  batch: string | null;
  soh: number | null;
  r: number | null;
  as_of: string;
  sel: RulForecastRow | undefined;
  byMethod: Partial<Record<RulMethod, RulForecastRow>>;
  risk: 'high' | 'watch' | 'ok';
}

const YEAR = 365.25;

/** Insights -> Battery health & safety -> RUL Forecast: remaining useful life per fleet unit (days and cycles to end
 *  of life, P10-P90), the unit's fade projection with what-if duty / temperature, survival curves, and the
 *  leave-one-unit-out backtest. */
@Component({
  selector: 'app-rul',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink, ChartCanvasComponent],
  templateUrl: './rul.component.html',
  styleUrls: [
    '../soh-estimator/soh-estimator.component.scss',
    '../price-forecast/price-forecast.component.scss',
    '../thermal-forecast/thermal-forecast.component.scss',
    '../aux-forecast/aux-forecast.component.scss',
    './rul.component.scss'
  ]
})
export class RulComponent implements OnInit {
  private auth = inject(AuthService);
  readonly labels = R_LABELS;
  readonly colors = R_COLORS;
  readonly order = R_ORDER;
  readonly Math = Math;

  models: RulModelOption[] = [];
  modelsLoaded = false;
  modelsError: string | null = null;
  modelKey = 'active';
  systems: RulSystem[] = [];
  tab: 'fleet' | 'unit' | 'backtest' = 'fleet';
  method: RulMethod = 'physics';

  forecasts: RulForecastRow[] = [];
  fleetLoading = false;
  fleetCfg?: AnyConfig;
  fleetRows: FleetRow[] = [];

  unitId: number | null = null;
  cpd: number | null = null;
  temp: number | null = null;
  prediction: RulPrediction | null = null;
  unitLoading = false;
  unitError: string | null = null;
  sohCfg?: AnyConfig;
  resCfg?: AnyConfig;
  survCfg?: AnyConfig;

  btShow = new Set<RulMethod>(['physics', 'hybrid', 'rsf']);
  btBand: RulMethod = 'physics';
  btCycles = false;
  btLoading = false;
  btCfg?: AnyConfig;
  btPoints: RulBacktestPoint[] = [];

  constructor(private service: RulService, private route: ActivatedRoute, private router: Router) {}

  ngOnInit(): void {
    const q = this.route.snapshot.queryParamMap;
    this.service.options().subscribe({ next: (o) => (this.systems = o.systems), error: () => (this.systems = []) });
    this.service.models().subscribe({
      next: (models) => {
        this.models = models;
        this.modelsLoaded = true;
        const wanted = q.get('model');
        this.modelKey = wanted && models.some((m) => String(m.run_id) === wanted) ? wanted : 'active';
        const run = this.run;
        if (run) {
          this.method = run.methods.includes('physics') ? 'physics' : run.methods[0];
          this.btShow = new Set(run.methods.filter((m) => ['physics', 'hybrid', 'rsf'].includes(m)));
          this.btBand = this.method;
          const u = Number(q.get('unit'));
          if (u) {
            this.unitId = u;
            this.tab = (q.get('tab') as any) || 'unit';
          }
          this.loadFleet();
          if (this.tab === 'unit') {
            this.loadUnit();
          } else if (this.tab === 'backtest') {
            this.loadBacktest();
          }
        }
      },
      error: (err) => {
        this.modelsLoaded = true;
        this.modelsError = err?.status === 0 ? 'Could not reach the ML service. Is it running on port 8100?' : 'Could not load the models.';
      }
    });
  }

  get run(): RulModelOption | undefined {
    return this.modelKey === 'active' ? this.models[0] : this.models.find((m) => String(m.run_id) === this.modelKey);
  }

  get runMethods(): RulMethod[] {
    return R_ORDER.filter((m) => this.run?.methods.includes(m));
  }

  optionLabel(m: RulModelOption): string {
    const mae = m.metrics?.['physics']?.['all']?.mae_days;
    return `#${m.run_id}${m.run_name ? ' ' + m.run_name : ''}${m.is_default ? ' (default)' : ''} · ${m.n_units ?? '—'} units · ${m.methods.length} methods${
      typeof mae === 'number' ? ` · physics MAE ${Math.round(mae)} d` : ''
    }`;
  }

  selectModel(key: string): void {
    this.modelKey = key;
    const run = this.run;
    if (run && !run.methods.includes(this.method)) {
      this.method = run.methods[0];
    }
    this.loadFleet();
    if (this.tab === 'unit') {
      this.loadUnit();
    } else if (this.tab === 'backtest') {
      this.loadBacktest();
    }
  }

  setTab(t: 'fleet' | 'unit' | 'backtest'): void {
    this.tab = t;
    if (t !== 'fleet' && !this.unitId) {
      this.unitId = this.fleetRows[0]?.system_id ?? this.systems.find((s) => s.snapshots)?.system_id ?? null;
    }
    this.syncUrl();
    if (t === 'unit') {
      this.loadUnit();
    } else if (t === 'backtest') {
      this.loadBacktest();
    }
  }

  openUnit(id: number): void {
    this.unitId = id;
    this.cpd = this.temp = null;
    this.setTab('unit');
  }

  selectUnit(id: number): void {
    this.unitId = id;
    this.cpd = this.temp = null;
    this.syncUrl();
    this.tab === 'unit' ? this.loadUnit() : this.loadBacktest();
  }

  private syncUrl(): void {
    this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { model: this.modelKey === 'active' ? null : this.modelKey, unit: this.tab === 'fleet' ? null : this.unitId, tab: this.tab === 'fleet' ? null : this.tab },
      replaceUrl: true
    });
  }

  unitLabel(s: RulSystem): string {
    const status = (s.end_events ?? '').includes('FAILURE') ? 'failed' : s.retired ? 'retired' : 'in service';
    return `${s.system_code} · ${s.batch_lot ?? '—'} · ${status}`;
  }

  // ---------------------------------------------------------------- fleet

  loadFleet(): void {
    const run = this.run;
    if (!run) {
      return;
    }
    this.fleetLoading = true;
    this.service.forecasts(run.run_id).subscribe({
      next: (rows) => {
        this.forecasts = rows;
        this.fleetLoading = false;
        this.buildFleet();
      },
      error: () => (this.fleetLoading = false)
    });
  }

  setMethod(m: RulMethod): void {
    this.method = m;
    this.buildFleet();
    if (this.tab === 'unit') {
      this.buildUnitCharts();
    }
  }

  buildFleet(): void {
    const by = new Map<number, FleetRow>();
    for (const f of this.forecasts) {
      const row = by.get(f.system_id) ?? {
        system_id: f.system_id,
        code: f.system_code,
        batch: this.systems.find((s) => s.system_id === f.system_id)?.batch_lot ?? null,
        soh: f.soh_pct,
        r: f.resistance_ratio,
        as_of: f.as_of,
        sel: undefined,
        byMethod: {},
        risk: 'ok'
      };
      row.byMethod[f.method] = f;
      by.set(f.system_id, row);
    }
    this.fleetRows = Array.from(by.values()).map((r) => {
      const sel = r.byMethod[this.method];
      const p10 = sel?.p10_days ?? Infinity;
      const p50 = sel?.p50_days ?? Infinity;
      return { ...r, sel, risk: p50 < YEAR / 2 ? 'high' : p10 < YEAR ? 'watch' : 'ok' };
    });
    this.fleetRows.sort((a, b) => (a.sel?.p50_days ?? Infinity) - (b.sel?.p50_days ?? Infinity));
    const bars = this.fleetRows
      .filter((r) => r.sel && r.sel.p50_days !== null)
      .map((r) => ({ code: r.code, p10: r.sel!.p10_days ?? 0, p50: r.sel!.p50_days ?? 0, p90: r.sel!.p90_days ?? 0, beyond: r.sel!.beyond }));
    this.fleetCfg = bars.length ? fleetChart(bars, R_COLORS[this.method]) : undefined;
  }

  get fleetKpis() {
    const live = this.fleetRows.filter((r) => r.sel);
    const soonest = live[0];
    return {
      live: live.length,
      retired: this.systems.filter((s) => s.retired).length,
      soonest,
      high: live.filter((r) => r.risk === 'high').length,
      watch: live.filter((r) => r.risk === 'watch').length
    };
  }

  // ---------------------------------------------------------------- unit

  loadUnit(): void {
    const run = this.run;
    if (!run || !this.unitId) {
      return;
    }
    this.unitLoading = true;
    this.unitError = null;
    if (!this.auth.hasPermission('ml.run:execute')) {
      this.unitLoading = false;
      this.unitError = WHAT_IF_TRAINERS_ONLY;
      return;
    }
    this.service.predict(this.modelKey, this.unitId, this.cpd, this.temp).subscribe({
      next: (p) => {
        this.prediction = p;
        this.unitLoading = false;
        this.buildUnitCharts();
      },
      error: (err) => {
        this.unitLoading = false;
        this.prediction = null;
        this.unitError = err?.error?.detail || 'Could not predict this unit.';
      }
    });
  }

  resetWhatIf(): void {
    this.cpd = this.temp = null;
    this.loadUnit();
  }

  get whatIfActive(): boolean {
    return this.cpd !== null || this.temp !== null;
  }

  result(m: RulMethod): RulMethodResult | undefined {
    return this.prediction?.methods[m];
  }

  buildUnitCharts(): void {
    const p = this.prediction;
    if (!p) {
      return;
    }
    const now = yearOf(p.as_of);
    const fut = (d: number) => now + d / YEAR;
    const hist = (k: 'soh_pct' | 'r_ratio'): XY[] => p.history.map((h) => ({ x: yearOf(h.date), y: h[k] }));
    const rpt = (k: 'soh_pct' | 'r_ratio'): XY[] => p.rpt.map((h) => ({ x: yearOf(h.date), y: h[k] }));
    const path = p.paths;
    const bandColor = R_COLORS.physics;
    if (path) {
      // the faster-fading path (P10 RUL) is the lower SOH / higher resistance one
      this.sohCfg = healthChart({
        unit: '% SOH',
        digits: 1,
        history: hist('soh_pct'),
        rpt: rpt('soh_pct'),
        p50: path.days.map((d, i) => ({ x: fut(d), y: path.soh_p50[i] })),
        band: path.days.map((d, i) => ({ x: fut(d), lo: path.soh_p10[i], hi: path.soh_p90[i] })),
        eol: p.eol.soh_eol_pct,
        eolLabel: `EOL ${p.eol.soh_eol_pct} % SOH`,
        now,
        bandColor
      });
      this.resCfg = path.r_p50
        ? healthChart({
            unit: '× BOL',
            digits: 2,
            history: hist('r_ratio'),
            rpt: rpt('r_ratio'),
            p50: path.days.map((d, i) => ({ x: fut(d), y: path.r_p50![i] })),
            band: path.days.map((d, i) => ({ x: fut(d), lo: path.r_p90![i], hi: path.r_p10![i] })),
            eol: p.eol.resistance_eol_pct ? p.eol.resistance_eol_pct / 100 : null,
            eolLabel: `EOL ${p.eol.resistance_eol_pct ? p.eol.resistance_eol_pct / 100 : '—'}× BOL resistance`,
            now,
            bandColor
          })
        : undefined;
    } else {
      this.sohCfg = this.resCfg = undefined;
    }
    const curves = (['cox', 'rsf'] as RulMethod[])
      .filter((m) => p.methods[m]?.survival?.length)
      .map((m) => ({ method: m, points: p.methods[m]!.survival! }));
    this.survCfg = curves.length ? survivalChart(curves) : undefined;
  }

  // ---------------------------------------------------------------- backtest

  toggleBt(m: RulMethod): void {
    const s = new Set(this.btShow);
    s.has(m) ? s.delete(m) : s.add(m);
    this.btShow = s;
    this.loadBacktest();
  }

  loadBacktest(): void {
    const run = this.run;
    if (!run || !this.unitId) {
      return;
    }
    const methods = Array.from(new Set([this.btBand, ...this.btShow])).filter((m) => run.methods.includes(m));
    this.btLoading = true;
    this.service.backtest(run.run_id, this.unitId, methods).subscribe({
      next: (pts) => {
        this.btPoints = pts;
        this.btLoading = false;
        this.buildBacktest();
      },
      error: () => (this.btLoading = false)
    });
  }

  buildBacktest(): void {
    const pts = this.btPoints;
    if (!pts.length) {
      this.btCfg = undefined;
      return;
    }
    const cyc = this.btCycles;
    const ref = pts.filter((p) => p.method === this.btBand);
    const any = ref.length ? ref : pts.filter((p) => p.method === pts[0].method);
    const censored = any[0].censored;
    const ratio = (p: RulBacktestPoint) => (p.p50_days ? (p.p50_cycles ?? 0) / p.p50_days : 0);
    const val = (p: RulBacktestPoint, d: number | null) => (d === null ? null : cyc ? d * ratio(p) : d);
    this.btCfg = backtestChart({
      unit: cyc ? 'cycles' : 'days',
      actual: any.map((p) => ({ x: yearOf(p.snapshot_date), y: censored ? val(p, p.known_alive_days) : cyc ? p.actual_cycles : p.actual_days })),
      actualLabel: censored ? 'Known alive at least (censored)' : 'True RUL',
      oracle: censored ? any.map((p) => ({ x: yearOf(p.snapshot_date), y: cyc ? p.actual_cycles : p.actual_days })) : undefined,
      lines: R_ORDER.filter((m) => this.btShow.has(m) || m === this.btBand).map((m) => ({
        method: m,
        points: pts.filter((p) => p.method === m).map((p) => ({ x: yearOf(p.snapshot_date), y: val(p, p.p50_days) }))
      })),
      band: ref.length
        ? { method: this.btBand, points: ref.map((p) => ({ x: yearOf(p.snapshot_date), lo: val(p, p.p10_days), hi: val(p, p.p90_days) })) }
        : undefined
    });
  }

  get btUnit(): RulSystem | undefined {
    return this.systems.find((s) => s.system_id === this.unitId);
  }

  unitMetric(m: RulMethod) {
    const code = this.btUnit?.system_code;
    return code ? this.run?.metrics?.[m]?.[`unit:${code}`] : undefined;
  }

  // ---------------------------------------------------------------- formatting

  num(v: number | null | undefined, d = 0): string {
    return typeof v === 'number' && Number.isFinite(v) ? v.toFixed(d) : '—';
  }

  years(days: number | null | undefined): string {
    return typeof days === 'number' && Number.isFinite(days) ? (days / YEAR).toFixed(1) : '—';
  }
}
