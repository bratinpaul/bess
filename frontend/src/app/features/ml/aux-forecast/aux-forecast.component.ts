import { CommonModule } from '@angular/common';
import { Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';

import {
  AuxAmbientSource,
  AuxBacktestPoint,
  AuxDailyRow,
  AuxMethod,
  AuxModelOption,
  AuxPlanSource,
  AuxPrediction,
  AuxSite
} from '../../../core/models/aux-forecast.model';
import { AuxForecastService } from '../../../core/services/aux-forecast.service';
import { ChartCanvasComponent } from '../../telemetry/graphs/chart-canvas.component';
import { A_COLORS, A_DASH, A_LABELS, A_ORDER, ACTUAL, HVAC, SeriesLine, bandChart, energyBars } from '../aux-forecast-shared/aux-charts';
import { AnyConfig, ms, plantLabel } from '../price-forecast-shared/pf-charts';

const REPORT_HORIZONS = [60, 120, 240, 360, 720, 1440];

/** Insights -> Forecasting -> Aux / HVAC Energy Forecast: the site's parasitic draw (HVAC + controls) over the next hours
 *  (P10-P90) with the aux energy per interval and day, and the backtest (trajectories, fixed horizon, daily energy). */
@Component({
  selector: 'app-aux-forecast',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink, ChartCanvasComponent],
  templateUrl: './aux-forecast.component.html',
  styleUrls: [
    '../soh-estimator/soh-estimator.component.scss',
    '../price-forecast/price-forecast.component.scss',
    '../thermal-forecast/thermal-forecast.component.scss',
    './aux-forecast.component.scss'
  ]
})
export class AuxForecastComponent implements OnInit {
  readonly methodLabels = A_LABELS;
  readonly methodColors = A_COLORS;
  readonly methods = A_ORDER;

  models: AuxModelOption[] = [];
  modelsLoaded = false;
  modelsError: string | null = null;
  modelKey = 'active';
  sites: AuxSite[] = [];
  emsId: number | null = null;
  tab: 'live' | 'backtest' = 'live';

  horizonHours = 24;
  planSource: AuxPlanSource = 'scheduled';
  ambientSource: AuxAmbientSource = 'forecast';
  asOf = '';
  enforceAge = false;
  prediction: AuxPrediction | null = null;
  loading = false;
  error: string | null = null;
  mainChart?: AnyConfig;
  ambientChart?: AnyConfig;
  planChart?: AnyConfig;
  showTable = false;

  btMode: 'trajectory' | 'horizon' | 'daily' = 'trajectory';
  btShow = new Set<AuxMethod>(['seasonal', 'greybox', 'hybrid']);
  btLoading = false;
  btCfg?: AnyConfig;
  origins: string[] = [];
  originIdx = 0;
  btHorizon = 360;
  btDays = 2;
  btOffset = 0;
  private btAll: AuxBacktestPoint[] = [];
  dailyRows: AuxDailyRow[] = [];

  constructor(private service: AuxForecastService, private route: ActivatedRoute, private router: Router) {}

  ngOnInit(): void {
    const q = this.route.snapshot.queryParamMap;
    this.service.options().subscribe({ next: (o) => (this.sites = o.sites), error: () => (this.sites = []) });
    this.service.models().subscribe({
      next: (models) => {
        this.models = models;
        this.modelsLoaded = true;
        const wanted = q.get('model');
        this.modelKey = wanted && models.some((m) => String(m.run_id) === wanted) ? wanted : 'active';
        const run = this.run;
        if (run) {
          const e = Number(q.get('site'));
          this.emsId = run.ems_ids.includes(e) ? e : run.ems_ids.includes(8) ? 8 : run.ems_ids[0];
          this.horizonHours = run.horizon_hours;
          this.btHorizon = this.horizonChoices.includes(360) ? 360 : this.horizonChoices[this.horizonChoices.length - 1];
          this.load();
        }
      },
      error: (err) => {
        this.modelsLoaded = true;
        this.modelsError = err?.status === 0 ? 'Could not reach the ML service. Is it running on port 8100?' : 'Could not load the models.';
      }
    });
  }

  get run(): AuxModelOption | undefined {
    return this.modelKey === 'active' ? this.models[0] : this.models.find((m) => String(m.run_id) === this.modelKey);
  }

  get horizonChoices(): number[] {
    const max = (this.run?.horizon_hours ?? 24) * 60;
    return REPORT_HORIZONS.filter((h) => h <= max);
  }

  get liveHorizons(): number[] {
    return [1, 2, 4, 6, 12, 24].filter((h) => h <= (this.run?.horizon_hours ?? 24));
  }

  optionLabel(m: AuxModelOption): string {
    return `#${m.run_id}${m.run_name ? ' ' + m.run_name : ''}${m.is_default ? ' (default)' : ''} · ${m.ems_ids.length} sites · ${m.horizon_hours} h`;
  }

  siteLabel(id: number): string {
    const s = this.sites.find((x) => x.ems_id === id);
    return s ? `${s.site_name} · ${s.system_name}` : `EMS ${id}`;
  }

  selectModel(key: string): void {
    this.modelKey = key;
    const run = this.run;
    if (run && (!this.emsId || !run.ems_ids.includes(this.emsId))) {
      this.emsId = run.ems_ids[0];
    }
    if (run) {
      this.horizonHours = Math.min(this.horizonHours, run.horizon_hours);
    }
    this.load();
  }

  selectSite(id: number): void {
    this.emsId = id;
    this.load();
  }

  setTab(t: 'live' | 'backtest'): void {
    this.tab = t;
    if (t === 'backtest') {
      this.loadBacktest();
    }
  }

  private load(): void {
    this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { model: this.modelKey === 'active' ? null : this.modelKey, site: this.emsId },
      replaceUrl: true
    });
    this.loadPrediction();
    if (this.tab === 'backtest') {
      this.loadBacktest();
    }
  }

  // ---------------------------------------------------------------- live

  loadPrediction(): void {
    const run = this.run;
    if (!run || !this.emsId) {
      return;
    }
    this.loading = true;
    this.error = null;
    this.service
      .predict(this.modelKey, {
        ems_id: this.emsId,
        horizon_hours: this.horizonHours,
        plan_source: this.planSource,
        ambient_source: this.ambientSource,
        as_of: this.asOf ? `${this.asOf}:00+05:30` : null,
        max_data_age_min: this.enforceAge ? 60 : null
      })
      .subscribe({
        next: (p) => {
          this.prediction = p;
          this.loading = false;
          this.buildLive();
        },
        error: (err) => {
          this.loading = false;
          this.prediction = null;
          this.mainChart = this.ambientChart = this.planChart = undefined;
          this.error = err?.error?.detail || 'Could not forecast.';
        }
      });
  }

  /** Jump to a past origin (the actuals that followed are drawn), e.g. a backtest origin. */
  forecastFrom(originIso: string | null): void {
    this.asOf = originIso ? originIso.slice(0, 16) : '';
    this.tab = 'live';
    this.loadPrediction();
  }

  get stale(): boolean {
    return !!this.prediction && (this.prediction.flags.stale || this.prediction.flags.missing_inputs.length > 0);
  }

  get hasActuals(): boolean {
    return !!this.prediction?.forecasts.some((f) => f.actual_kw !== null && f.actual_kw !== undefined);
  }

  private buildLive(): void {
    const p = this.prediction;
    if (!p) {
      return;
    }
    const origin = ms(p.origin_ts);
    const hist = p.history.aux_load_kw.map((h) => ({ x: ms(h.ts), y: h.v }));
    const now = hist.length ? hist[hist.length - 1].y : null;
    const f = p.forecasts;
    const at = f.map((r) => ms(r.ts_target));
    const after = f.map((r, i) => ({ x: at[i], y: r.actual_kw ?? null })).filter((pt) => pt.y !== null);
    if (this.stale) {
      this.mainChart = bandChart({ unit: 'kW', actual: [...hist, ...after], lines: [], originMs: origin, beginAtZero: true });
    } else {
      const lines: SeriesLine[] = [
        { label: 'HVAC (measured)', color: HVAC, width: 1.2, points: p.history.hvac_power_kw.map((h) => ({ x: ms(h.ts), y: h.v })) },
        { label: 'Forecast P50', color: A_COLORS.hybrid, width: 2.4, points: [{ x: origin, y: now }, ...f.map((r, i) => ({ x: at[i], y: r.aux_kw_p50 }))] },
        { label: A_LABELS.greybox, color: A_COLORS.greybox, dash: A_DASH.greybox, width: 1.4, points: f.map((r, i) => ({ x: at[i], y: r.greybox_kw ?? null })) },
        { label: A_LABELS.seasonal, color: A_COLORS.seasonal, dash: A_DASH.seasonal, width: 1.4, points: f.map((r, i) => ({ x: at[i], y: r.seasonal_kw ?? null })) }
      ];
      this.mainChart = bandChart({
        unit: 'kW',
        actual: [...hist, ...after],
        band: { label: 'Forecast', color: A_COLORS.hybrid, points: [{ x: origin, lo: now, hi: now }, ...f.map((r, i) => ({ x: at[i], lo: r.aux_kw_p10, hi: r.aux_kw_p90 }))] },
        lines,
        originMs: origin,
        beginAtZero: true
      });
    }
    const ambHist = p.history.ambient_temp_c.map((h) => ({ x: ms(h.ts), y: h.v }));
    const ambNow = ambHist.length ? ambHist[ambHist.length - 1].y : null;
    this.ambientChart = bandChart({
      unit: '°C',
      actual: ambHist,
      lines: [
        {
          label: `Ambient ahead (${this.ambientLabel(p.ambient_source)})`,
          color: '#c47a00',
          width: 1.8,
          points: [{ x: origin, y: ambNow }, ...f.map((r, i) => ({ x: at[i], y: r.ambient_fc_c ?? null }))]
        }
      ],
      originMs: origin
    });
    this.planChart = bandChart({
      unit: 'kW',
      digits: 0,
      lines: [{ label: `Planned dispatch (${p.plan_source === 'scheduled' ? 'schedule' : 'typical day'})`, color: '#2a78d6', width: 1.6, points: f.map((r, i) => ({ x: at[i], y: r.plan_kw ?? null })) }],
      originMs: origin
    });
  }

  ambientLabel(s: AuxAmbientSource): string {
    return s === 'forecast' ? 'weather forecast / profile' : s === 'profile' ? 'daily profile' : 'measured';
  }

  get kpis() {
    const p = this.prediction;
    if (!p || this.stale) {
      return null;
    }
    const f = p.forecasts.filter((r) => r.aux_kw_p50 !== null);
    const first = f.slice(0, 12);
    const avg1h = first.reduce((a, r) => a + (r.aux_kw_p50 ?? 0), 0) / Math.max(1, first.length);
    const peak = f.reduce((b, r) => ((r.aux_kw_p50 ?? -1) > (b?.aux_kw_p50 ?? -1) ? r : b), f[0]);
    const kwh = 5 / 60;
    const sum = (k: 'aux_kw_p10' | 'aux_kw_p50' | 'aux_kw_p90') => f.reduce((a, r) => a + (r[k] ?? 0) * kwh, 0);
    const act = f.filter((r) => r.actual_kw !== null && r.actual_kw !== undefined);
    const hvac = f.reduce((a, r) => a + (r.hvac_kw_p50 ?? 0), 0) / Math.max(1, f.length);
    const fromFc = f.filter((r) => r.ambient_from_forecast).length / Math.max(1, f.length);
    const hist = p.history.aux_load_kw;
    return {
      now: hist.length ? hist[hist.length - 1].v : null,
      avg1h,
      peak,
      e50: sum('aux_kw_p50'),
      e10: sum('aux_kw_p10'),
      e90: sum('aux_kw_p90'),
      actualKwh: act.length === f.length ? act.reduce((a, r) => a + (r.actual_kw ?? 0) * kwh, 0) : null,
      hvacAvg: p.greybox.decomposed ? hvac : null,
      controls: p.greybox.decomposed ? p.greybox.controls_base_kw : null,
      fromFcPct: fromFc * 100
    };
  }

  get dataAge(): string {
    const a = this.prediction?.data_age_min;
    if (a === null || a === undefined) {
      return '';
    }
    return a < 90 ? `${Math.round(a)} min` : a < 2880 ? `${(a / 60).toFixed(1)} h` : `${(a / 1440).toFixed(1)} days`;
  }

  time(iso: string | null | undefined): string {
    return iso ? plantLabel(ms(iso)) : '';
  }

  num(v: number | null | undefined, d = 1): string {
    return typeof v === 'number' && Number.isFinite(v) ? v.toFixed(d) : '—';
  }

  signed(v: number | null | undefined, d = 1): string {
    return typeof v === 'number' && Number.isFinite(v) ? `${v > 0 ? '+' : ''}${v.toFixed(d)}` : '—';
  }

  // ---------------------------------------------------------------- backtest

  setBtMode(m: 'trajectory' | 'horizon' | 'daily'): void {
    this.btMode = m;
    this.loadBacktest();
  }

  toggleMethod(m: AuxMethod): void {
    const s = new Set(this.btShow);
    s.has(m) ? s.delete(m) : s.add(m);
    this.btShow = s;
    this.loadBacktest();
  }

  loadBacktest(): void {
    const run = this.run;
    if (!run || !this.emsId) {
      return;
    }
    const methods = Array.from(new Set(['hybrid', ...this.btShow]));
    this.btLoading = true;
    if (this.btMode === 'daily') {
      this.service.daily(run.run_id, this.emsId).subscribe({
        next: (rows) => {
          this.dailyRows = rows;
          this.btLoading = false;
          this.buildDaily();
        },
        error: () => (this.btLoading = false)
      });
      return;
    }
    if (this.btMode === 'horizon') {
      this.service.series(run.run_id, this.emsId, this.btHorizon, methods).subscribe({
        next: (pts) => {
          this.btAll = pts;
          this.btLoading = false;
          this.btOffset = Math.min(this.btOffset, Math.max(0, this.btSpanDays - this.btDays));
          this.buildHorizon();
        },
        error: () => (this.btLoading = false)
      });
      return;
    }
    const fetch = (list: string[]) => {
      this.origins = list;
      if (!list.length) {
        this.btLoading = false;
        this.btCfg = undefined;
        return;
      }
      this.originIdx = Math.min(this.originIdx, list.length - 1);
      this.service.trajectory(run.run_id, this.emsId!, list[this.originIdx], methods).subscribe({
        next: (pts) => {
          this.btAll = pts;
          this.btLoading = false;
          this.buildTrajectory();
        },
        error: () => (this.btLoading = false)
      });
    };
    if (this.origins.length && this.originsFor === `${run.run_id}|${this.emsId}`) {
      fetch(this.origins);
    } else {
      this.originsFor = `${run.run_id}|${this.emsId}`;
      this.service.origins(run.run_id, this.emsId).subscribe({
        next: (list) => {
          // start on the first forecast issued at 23:55 (a full next day)
          const i = list.findIndex((o) => o.slice(11, 16) === '23:55');
          this.originIdx = i >= 0 ? i : 0;
          fetch(list);
        },
        error: () => (this.btLoading = false)
      });
    }
  }

  private originsFor = '';

  stepOrigin(d: number): void {
    this.originIdx = Math.max(0, Math.min(this.origins.length - 1, this.originIdx + d));
    this.loadBacktest();
  }

  get currentOrigin(): string | null {
    return this.origins[this.originIdx] ?? null;
  }

  private buildTrajectory(): void {
    const origin = this.currentOrigin;
    if (!origin || !this.btAll.length) {
      this.btCfg = undefined;
      return;
    }
    const hybrid = this.btAll.filter((p) => p.method === 'hybrid');
    this.btCfg = bandChart({
      unit: 'kW',
      actual: hybrid.map((p) => ({ x: ms(p.target_ts), y: p.actual })),
      band: { label: 'Hybrid', color: A_COLORS.hybrid, points: hybrid.map((p) => ({ x: ms(p.target_ts), lo: p.p10, hi: p.p90 })) },
      lines: this.methodLines(this.btAll),
      originMs: ms(origin),
      beginAtZero: true
    });
  }

  get trajectoryEnergy(): { method: AuxMethod; kwh: number; actual: number }[] {
    if (this.btMode !== 'trajectory' || !this.btAll.length) {
      return [];
    }
    const kwh = 5 / 60;
    return A_ORDER.filter((m) => this.btShow.has(m) || m === 'hybrid')
      .map((m) => {
        const pts = this.btAll.filter((p) => p.method === m);
        return {
          method: m,
          kwh: pts.reduce((a, p) => a + (p.p50 ?? 0) * kwh, 0),
          actual: pts.reduce((a, p) => a + (p.actual ?? 0) * kwh, 0)
        };
      })
      .filter((x) => x.kwh > 0);
  }

  private methodLines(pts: AuxBacktestPoint[]): SeriesLine[] {
    return A_ORDER.filter((m) => this.btShow.has(m) || m === 'hybrid').map((m) => ({
      label: `${A_LABELS[m]} P50`,
      color: A_COLORS[m],
      dash: A_DASH[m],
      width: m === 'hybrid' ? 2 : 1.3,
      points: pts.filter((p) => p.method === m).map((p) => ({ x: ms(p.target_ts), y: p.p50 }))
    }));
  }

  get btSpanDays(): number {
    if (!this.btAll.length) {
      return 0;
    }
    const xs = this.btAll.map((p) => ms(p.target_ts));
    return Math.ceil((Math.max(...xs) - Math.min(...xs)) / 86400e3);
  }

  shiftWindow(d: number): void {
    this.btOffset = Math.max(0, Math.min(this.btOffset + d, Math.max(0, this.btSpanDays - this.btDays)));
    this.buildHorizon();
  }

  buildHorizon(): void {
    if (!this.btAll.length) {
      this.btCfg = undefined;
      return;
    }
    const start = Math.min(...this.btAll.map((p) => ms(p.target_ts))) + this.btOffset * 86400e3;
    const end = start + this.btDays * 86400e3;
    const inWin = this.btAll.filter((p) => ms(p.target_ts) >= start && ms(p.target_ts) < end);
    const hybrid = inWin.filter((p) => p.method === 'hybrid');
    this.btCfg = bandChart({
      unit: 'kW',
      actual: hybrid.map((p) => ({ x: ms(p.target_ts), y: p.actual })),
      band: { label: 'Hybrid', color: A_COLORS.hybrid, points: hybrid.map((p) => ({ x: ms(p.target_ts), lo: p.p10, hi: p.p90 })) },
      lines: this.methodLines(inWin),
      beginAtZero: true
    });
  }

  windowLabel(): string {
    if (!this.btAll.length) {
      return '';
    }
    const start = Math.min(...this.btAll.map((p) => ms(p.target_ts))) + this.btOffset * 86400e3;
    return `${plantLabel(start)} → ${plantLabel(start + this.btDays * 86400e3)}`;
  }

  private buildDaily(): void {
    const days = Array.from(new Set(this.dailyRows.map((r) => r.day))).sort();
    if (!days.length) {
      this.btCfg = undefined;
      return;
    }
    const pick = (m: AuxMethod, key: 'p50_kwh' | 'actual_kwh') =>
      days.map((d) => this.dailyRows.find((r) => r.day === d && r.method === m)?.[key] ?? null);
    const bars = [{ label: 'Actual', values: pick('hybrid', 'actual_kwh'), color: ACTUAL }];
    for (const m of A_ORDER.filter((x) => this.btShow.has(x) || x === 'hybrid')) {
      bars.push({ label: `${A_LABELS[m]} P50`, values: pick(m, 'p50_kwh'), color: m === 'seasonal' ? '#b9bdc4' : A_COLORS[m] });
    }
    this.btCfg = energyBars(
      days.map((d) => d.slice(5)),
      bars
    );
  }

  get dailyTable(): { day: string; actual: number | null; byMethod: Record<string, { p50: number | null; p10: number | null; p90: number | null }> }[] {
    const days = Array.from(new Set(this.dailyRows.map((r) => r.day))).sort();
    return days.map((d) => {
      const rows = this.dailyRows.filter((r) => r.day === d);
      return {
        day: d,
        actual: rows[0]?.actual_kwh ?? null,
        byMethod: Object.fromEntries(rows.map((r) => [r.method, { p50: r.p50_kwh, p10: r.p10_kwh, p90: r.p90_kwh }]))
      };
    });
  }

  metric(m: AuxMethod, bucket = 'all') {
    return this.run?.metrics?.[String(this.emsId)]?.[bucket]?.[m];
  }

  bucketOf(h: number): string {
    return h <= 60 ? '0-1 h' : h <= 120 ? '1-2 h' : h <= 240 ? '2-4 h' : h <= 480 ? '4-8 h' : h <= 720 ? '8-12 h' : '12-24 h';
  }
}
