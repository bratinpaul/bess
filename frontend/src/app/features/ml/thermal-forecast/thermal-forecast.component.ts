import { CommonModule } from '@angular/common';
import { Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';

import {
  ThermalForecastRow,
  ThermalMethod,
  ThermalModelOption,
  ThermalPrediction,
  ThermalSystem,
  ThermalTarget,
  ThermalTargetSpec
} from '../../../core/models/thermal-forecast.model';
import { ThermalForecastService } from '../../../core/services/thermal-forecast.service';
import { ChartCanvasComponent } from '../../telemetry/graphs/chart-canvas.component';
import { AnyConfig, ms, plantLabel } from '../price-forecast-shared/pf-charts';
import { T_COLORS, T_DASH, T_LABELS, T_ORDER, TempLine, tempChart } from '../thermal-forecast-shared/thermal-charts';

interface TargetCard {
  target: ThermalTarget;
  label: string;
  rows: ThermalForecastRow[];
  status: 'ALERT' | 'WATCH' | 'OK' | 'STALE';
  threshold: number | null;
  alarm: number | null;
  now: number | null;
  assetType: string;
  assetId: number | null;
  chart?: AnyConfig;
  flag: string | null;
}

/** Insights -> Forecasting -> Temperature Forecast: cell / coolant / IGBT / enclosure temperature over the next
 *  minutes per asset (P10-P90), with pre-alarm status, and the backtest per target and horizon. */
@Component({
  selector: 'app-thermal-forecast',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink, ChartCanvasComponent],
  templateUrl: './thermal-forecast.component.html',
  styleUrls: ['../soh-estimator/soh-estimator.component.scss', '../price-forecast/price-forecast.component.scss', './thermal-forecast.component.scss']
})
export class ThermalForecastComponent implements OnInit {
  readonly methodLabels = T_LABELS;
  readonly methodColors = T_COLORS;
  readonly methods = T_ORDER;

  models: ThermalModelOption[] = [];
  modelsLoaded = false;
  modelsError: string | null = null;
  modelKey = 'active';
  systems: ThermalSystem[] = [];
  targetSpecs: ThermalTargetSpec[] = [];
  catalog: Record<string, number | null> = {};
  systemId: number | null = null;
  tab: 'live' | 'backtest' = 'live';

  planSource: 'scheduled' | 'typical' = 'scheduled';
  enforceAge = false;
  prediction: ThermalPrediction | null = null;
  loading = false;
  error: string | null = null;
  cards: TargetCard[] = [];

  btTarget: ThermalTarget = 'cell_temp_max_c';
  btHorizon = 60;
  btShow = new Set<ThermalMethod>(['persistence', 'rc', 'hybrid']);
  btCfg?: AnyConfig;
  btLoading = false;
  btDays = 2;
  btOffset = 0; // days from the start of the test period
  private btAll: { method: ThermalMethod; target_ts: string; p10: number | null; p50: number | null; p90: number | null; actual: number | null }[] = [];

  constructor(private service: ThermalForecastService, private route: ActivatedRoute, private router: Router) {}

  ngOnInit(): void {
    const q = this.route.snapshot.queryParamMap;
    this.service.options().subscribe({
      next: (o) => {
        this.systems = o.systems;
        this.targetSpecs = o.targets;
        this.catalog = o.catalog_thresholds;
        this.buildCards();
      },
      error: () => (this.systems = [])
    });
    this.service.models().subscribe({
      next: (models) => {
        this.models = models;
        this.modelsLoaded = true;
        const wanted = q.get('model');
        this.modelKey = wanted && models.some((m) => String(m.run_id) === wanted) ? wanted : 'active';
        const run = this.run;
        if (run) {
          const sys = Number(q.get('system'));
          this.systemId = run.system_ids.includes(sys) ? sys : run.system_ids.includes(12) ? 12 : run.system_ids[0];
          this.btTarget = run.targets[0];
          this.btHorizon = Math.max(...run.horizons_min);
          this.load();
        }
      },
      error: (err) => {
        this.modelsLoaded = true;
        this.modelsError = err?.status === 0 ? 'Could not reach the ML service. Is it running on port 8100?' : 'Could not load the models.';
      }
    });
  }

  get run(): ThermalModelOption | undefined {
    return this.modelKey === 'active' ? this.models[0] : this.models.find((m) => String(m.run_id) === this.modelKey);
  }

  optionLabel(m: ThermalModelOption): string {
    return `#${m.run_id}${m.run_name ? ' ' + m.run_name : ''}${m.is_default ? ' (default)' : ''} · ${m.system_ids.length} systems · ${m.targets.length} targets · ${m.horizons_min.join('/')} min`;
  }

  systemLabel(id: number): string {
    const s = this.systems.find((x) => x.battery_system_id === id);
    return s ? `${s.site_name ?? s.system_name} · ${s.system_name}` : `System ${id}`;
  }

  targetLabel(t: string): string {
    return this.targetSpecs.find((x) => x.key === t)?.label ?? t;
  }

  selectModel(key: string): void {
    this.modelKey = key;
    const run = this.run;
    if (run && (!this.systemId || !run.system_ids.includes(this.systemId))) {
      this.systemId = run.system_ids[0];
    }
    if (run && !run.targets.includes(this.btTarget)) {
      this.btTarget = run.targets[0];
    }
    this.load();
  }

  selectSystem(id: number): void {
    this.systemId = id;
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
      queryParams: { model: this.modelKey === 'active' ? null : this.modelKey, system: this.systemId },
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
    if (!run || !this.systemId) {
      return;
    }
    this.loading = true;
    this.error = null;
    this.service.predict(this.modelKey, this.systemId, run.horizons_min, this.planSource, this.enforceAge ? 60 : null).subscribe({
      next: (p) => {
        this.prediction = p;
        this.loading = false;
        this.buildCards();
      },
      error: (err) => {
        this.loading = false;
        this.prediction = null;
        this.cards = [];
        this.error = err?.error?.detail || 'Could not forecast.';
      }
    });
  }

  private buildCards(): void {
    const p = this.prediction;
    if (!p) {
      return;
    }
    const origin = ms(p.origin_ts);
    const targets = Array.from(new Set(p.forecasts.map((f) => f.target)));
    this.cards = targets.map((t) => {
      const rows = p.forecasts.filter((f) => f.target === t).sort((a, b) => a.horizon_min - b.horizon_min);
      const thr = rows[0]?.threshold_c ?? this.targetSpecs.find((x) => x.key === t)?.threshold ?? null;
      const alarm = this.catalog[t] ?? null;
      const hist = p.history[t] ?? [];
      const now = hist.length ? hist[hist.length - 1].v : null;
      const stale = rows.some((r) => r.flag);
      const p50max = Math.max(...rows.map((r) => r.pred_c ?? -Infinity));
      const p90max = Math.max(...rows.map((r) => r.p90_c ?? -Infinity));
      const status: TargetCard['status'] = stale ? 'STALE' : thr !== null && p50max >= thr ? 'ALERT' : thr !== null && p90max >= thr ? 'WATCH' : 'OK';
      const at = (h: number) => origin + h * 60e3;
      const lines: TempLine[] = [
        { label: 'Forecast P50', color: T_COLORS.hybrid, width: 2.5, pointRadius: 4, points: [{ x: origin, y: now }, ...rows.map((r) => ({ x: at(r.horizon_min), y: r.pred_c }))] },
        { label: 'RC grey-box', color: T_COLORS.rc, dash: T_DASH.rc, width: 1.5, points: [{ x: origin, y: now }, ...rows.map((r) => ({ x: at(r.horizon_min), y: r.rc_c ?? null }))] }
      ];
      const card: TargetCard = {
        target: t,
        label: this.targetLabel(t),
        rows,
        status,
        threshold: thr,
        alarm,
        now,
        assetType: rows[0]?.asset_type ?? '',
        assetId: rows[0]?.asset_id ?? null,
        flag: rows.find((r) => r.flag)?.flag ?? null
      };
      if (!stale) {
        card.chart = tempChart({
          history: hist.map((h) => ({ x: ms(h.ts), y: h.v })),
          ambient: t === 'cell_temp_max_c' || t === 'enclosure_temp_c' ? p.ambient.map((h) => ({ x: ms(h.ts), y: h.v })) : [],
          band: {
            label: 'Forecast',
            color: T_COLORS.hybrid,
            points: [{ x: origin, lo: now, hi: now }, ...rows.map((r) => ({ x: at(r.horizon_min), lo: r.p10_c, hi: r.p90_c }))]
          },
          lines,
          originMs: origin,
          threshold: thr,
          alarm
        });
      }
      return card;
    });
  }

  get dataAge(): string {
    const a = this.prediction?.data_age_min;
    if (a === null || a === undefined) {
      return '';
    }
    return a < 90 ? `${Math.round(a)} min` : a < 2880 ? `${(a / 60).toFixed(1)} h` : `${(a / 1440).toFixed(1)} days`;
  }

  originTime(): string {
    return this.prediction ? plantLabel(ms(this.prediction.origin_ts)) : '';
  }

  num(v: number | null | undefined, d = 1): string {
    return typeof v === 'number' && Number.isFinite(v) ? v.toFixed(d) : '—';
  }

  pct(v: number | null | undefined): string {
    return typeof v === 'number' && Number.isFinite(v) ? `${Math.round(v * 100)} %` : '—';
  }

  // ---------------------------------------------------------------- backtest

  toggleMethod(m: ThermalMethod): void {
    const s = new Set(this.btShow);
    s.has(m) ? s.delete(m) : s.add(m);
    this.btShow = s;
    this.loadBacktest();
  }

  loadBacktest(): void {
    const run = this.run;
    if (!run || !this.systemId) {
      return;
    }
    const methods = Array.from(new Set(['hybrid', ...this.btShow]));
    this.btLoading = true;
    this.service.series(run.run_id, this.systemId, this.btTarget, this.btHorizon, methods).subscribe({
      next: (pts) => {
        this.btAll = pts;
        this.btLoading = false;
        this.btOffset = Math.min(this.btOffset, Math.max(0, this.btSpanDays - this.btDays));
        this.buildBacktest();
      },
      error: () => (this.btLoading = false)
    });
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
    this.buildBacktest();
  }

  buildBacktest(): void {
    if (!this.btAll.length) {
      this.btCfg = undefined;
      return;
    }
    const start = Math.min(...this.btAll.map((p) => ms(p.target_ts))) + this.btOffset * 86400e3;
    const end = start + this.btDays * 86400e3;
    const inWin = this.btAll.filter((p) => ms(p.target_ts) >= start && ms(p.target_ts) < end);
    const hybrid = inWin.filter((p) => p.method === 'hybrid');
    const lines: TempLine[] = [];
    for (const m of T_ORDER.filter((x) => this.btShow.has(x))) {
      lines.push({
        label: `${T_LABELS[m]} P50`,
        color: T_COLORS[m],
        dash: T_DASH[m],
        width: m === 'hybrid' ? 2 : 1.3,
        points: inWin.filter((p) => p.method === m).map((p) => ({ x: ms(p.target_ts), y: p.p50 }))
      });
    }
    const thr = this.metric('hybrid')?.threshold_c ?? null;
    this.btCfg = tempChart({
      history: hybrid.map((p) => ({ x: ms(p.target_ts), y: p.actual })),
      band: { label: 'Hybrid', color: T_COLORS.hybrid, points: hybrid.map((p) => ({ x: ms(p.target_ts), lo: p.p10, hi: p.p90 })) },
      lines,
      threshold: thr,
      alarm: this.catalog[this.btTarget] ?? null
    });
  }

  metric(m: ThermalMethod) {
    return this.run?.metrics?.[this.btTarget]?.[String(this.btHorizon)]?.[m];
  }

  windowLabel(): string {
    if (!this.btAll.length) {
      return '';
    }
    const start = Math.min(...this.btAll.map((p) => ms(p.target_ts))) + this.btOffset * 86400e3;
    return `${plantLabel(start)} → ${plantLabel(start + this.btDays * 86400e3)}`;
  }
}
