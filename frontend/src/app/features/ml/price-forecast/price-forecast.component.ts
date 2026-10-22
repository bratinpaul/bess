import { CommonModule } from '@angular/common';
import { Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';

import {
  PfBacktest,
  PfBand,
  PfForecast,
  PfForecastPoint,
  PfModelKey,
  PfModelOption,
  PfUnit
} from '../../../core/models/price-forecast.model';
import { PriceForecastService } from '../../../core/services/price-forecast.service';
import { ChartCanvasComponent } from '../../telemetry/graphs/chart-canvas.component';
import { AnyConfig, PF_COLORS, PF_LABELS, PF_ORDER, fanChart, ms, plantLabel, spikeChart } from '../price-forecast-shared/pf-charts';

interface HourRow {
  ts: string;
  label: string;
  band: PfBand | undefined;
  p: PfForecastPoint;
  action: 'charge' | 'discharge' | null;
}

const ACTION_HOURS = 3;

/** Insights -> Forecasting -> Price Forecast: the next 48 h price forecast per EMS (fan chart, spike risk,
 *  charge / discharge windows) and the backtests of a run. */
@Component({
  selector: 'app-price-forecast',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink, ChartCanvasComponent],
  templateUrl: './price-forecast.component.html',
  styleUrls: ['../soh-estimator/soh-estimator.component.scss', './price-forecast.component.scss']
})
export class PriceForecastComponent implements OnInit {
  readonly colors = PF_COLORS;
  readonly labels = PF_LABELS;

  models: PfModelOption[] = [];
  modelsLoaded = false;
  modelsError: string | null = null;
  modelKey = 'active';
  units: PfUnit[] = [];
  emsId: number | null = null;
  tab: 'live' | 'backtest' = 'live';

  chartModel: PfModelKey = 'lightgbm';
  compareAll = false;
  show5min = true;
  showMean = false;

  forecast: PfForecast | null = null;
  loading = false;
  error: string | null = null;
  fan?: AnyConfig;
  spike?: AnyConfig;
  rows: HourRow[] = [];

  origins: string[] = [];
  originIdx = 0;
  backtest: PfBacktest | null = null;
  btLoading = false;
  btError: string | null = null;
  btFan?: AnyConfig;
  btScores: { model: PfModelKey; mae: number; cover: number; n: number }[] = [];

  constructor(private service: PriceForecastService, private route: ActivatedRoute, private router: Router) {}

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
          this.chartModel = run.best_model ?? 'lightgbm';
          this.load();
        }
      },
      error: (err) => {
        this.modelsLoaded = true;
        this.modelsError = err?.status === 0 ? 'Could not reach the ML service. Is it running on port 8100?' : 'Could not load the models.';
      }
    });
  }

  // ---------------------------------------------------------------- pickers

  get run(): PfModelOption | undefined {
    return this.modelKey === 'active' ? this.models[0] : this.models.find((m) => String(m.run_id) === this.modelKey);
  }

  get runModels(): PfModelKey[] {
    return PF_ORDER.filter((k) => this.run?.models.includes(k));
  }

  optionLabel(m: PfModelOption): string {
    const best = m.best_model ? `${PF_LABELS[m.best_model]} MAE ${m.metrics?.[m.best_model]?.mae?.toFixed(2) ?? '—'}` : '';
    return `#${m.run_id}${m.run_name ? ' ' + m.run_name : ''}${m.is_default ? ' (default)' : ''} · ${m.ems_ids.length} EMS · ${best}`;
  }

  unitLabel(id: number): string {
    const u = this.units.find((x) => x.ems_id === id);
    return u ? `${u.site_name ?? u.system_name ?? 'EMS ' + id} · ${u.ems_code}` : `EMS ${id}`;
  }

  selectModel(key: string): void {
    this.modelKey = key;
    const run = this.run;
    if (run && (!this.emsId || !run.ems_ids.includes(this.emsId))) {
      this.emsId = run.ems_ids[0];
    }
    if (run && !run.models.includes(this.chartModel)) {
      this.chartModel = run.best_model ?? run.models[0];
    }
    this.load();
  }

  selectEms(id: number): void {
    this.emsId = id;
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

  // ---------------------------------------------------------------- live forecast

  loadForecast(): void {
    if (!this.emsId) {
      return;
    }
    this.loading = true;
    this.error = null;
    this.service.forecast(this.modelKey, this.emsId, 72).subscribe({
      next: (f) => {
        this.forecast = f;
        this.loading = false;
        if (!f.forecasts[this.chartModel]) {
          this.chartModel = (f.best_model as PfModelKey) ?? (Object.keys(f.forecasts)[0] as PfModelKey);
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

  setChartModel(k: PfModelKey): void {
    this.chartModel = k;
    this.buildLive();
    this.buildBacktest();
  }

  buildLive(): void {
    const f = this.forecast;
    const pts = f?.forecasts[this.chartModel];
    if (!f || !pts) {
      this.fan = undefined;
      return;
    }
    const others = this.compareAll ? this.runModels.filter((k) => k !== this.chartModel && f.forecasts[k]) : [];
    this.fan = fanChart({
      history: f.history.map((h) => ({ x: ms(h.ts), y: h.price })),
      history5: this.show5min ? f.history_5min.map((h) => ({ x: ms(h.ts), y: h.price })) : [],
      model: this.chartModel,
      forecast: pts.map((p) => ({ x: ms(p.target_ts), p10: p.p10, p50: p.p50, p90: p.p90, mean: p.mean })),
      overlays: others.map((k) => ({ model: k, points: f.forecasts[k].map((p) => ({ x: ms(p.target_ts), y: p.p50 })) })),
      originMs: ms(f.origin_ts) + 30 * 60 * 1000,
      bands: f.bands,
      showMean: this.showMean
    });
    const hs = f.history.map((h) => ms(h.ts));
    const fs = pts.map((p) => ms(p.target_ts));
    const spikePts = f.forecasts['spike_hybrid'];
    this.spike = spikePts
      ? spikeChart(spikePts.map((p) => ({ x: ms(p.target_ts), p: p.spike_prob })), Math.min(...hs, ...fs), Math.max(...hs, ...fs))
      : undefined;
    this.rows = this.hourRows(pts, f.bands);
  }

  private hourRows(pts: PfForecastPoint[], bands: PfBand[]): HourRow[] {
    const next24 = pts.filter((p) => p.horizon <= 24 && p.p50 !== null);
    const sorted = [...next24].sort((a, b) => (a.p50 ?? 0) - (b.p50 ?? 0));
    const cheap = new Set(sorted.slice(0, ACTION_HOURS).map((p) => p.target_ts));
    const dear = new Set(sorted.slice(-ACTION_HOURS).map((p) => p.target_ts));
    const spikes = this.forecast?.forecasts['spike_hybrid'];
    return pts.map((p) => {
      const hour = Number(plantLabel(ms(p.target_ts), false).slice(0, 2));
      const sp = spikes?.find((s) => s.target_ts === p.target_ts)?.spike_prob ?? p.spike_prob;
      return {
        ts: p.target_ts,
        label: plantLabel(ms(p.target_ts)),
        band: bands.find((b) => hour >= b.start_hour && hour < b.end_hour),
        p: { ...p, spike_prob: sp },
        action: cheap.has(p.target_ts) ? 'charge' : dear.has(p.target_ts) ? 'discharge' : null
      };
    });
  }

  get summary() {
    const pts = this.forecast?.forecasts[this.chartModel]?.filter((p) => p.horizon <= 24 && p.p50 !== null) ?? [];
    if (!pts.length) {
      return null;
    }
    const byP = [...pts].sort((a, b) => (a.p50 ?? 0) - (b.p50 ?? 0));
    const cheap = byP.slice(0, ACTION_HOURS);
    const dear = byP.slice(-ACTION_HOURS);
    const avg = (xs: PfForecastPoint[]) => xs.reduce((s, p) => s + (p.p50 ?? 0), 0) / xs.length;
    const spikes = this.forecast?.forecasts['spike_hybrid']?.filter((p) => p.horizon <= 24) ?? [];
    const risk = spikes.length ? spikes.reduce((b, p) => ((p.spike_prob ?? 0) > (b.spike_prob ?? 0) ? p : b)) : null;
    return {
      min: byP[0],
      max: byP[byP.length - 1],
      chargeAvg: avg(cheap),
      dischargeAvg: avg(dear),
      spread: avg(dear) - avg(cheap),
      charge: cheap.map((p) => plantLabel(ms(p.target_ts), false)).sort(),
      discharge: dear.map((p) => plantLabel(ms(p.target_ts), false)).sort(),
      risk
    };
  }

  get modelScore() {
    return this.run?.metrics?.[this.chartModel] ?? null;
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
    this.btLoading = true;
    this.btError = null;
    this.service.backtest(run.run_id, this.emsId, o).subscribe({
      next: (b) => {
        this.backtest = b;
        this.btLoading = false;
        this.buildBacktest();
      },
      error: (err) => {
        this.btLoading = false;
        this.btError = err?.error?.detail || 'Could not load the backtest.';
      }
    });
  }

  buildBacktest(): void {
    const b = this.backtest;
    if (!b) {
      this.btFan = undefined;
      return;
    }
    const of = (k: PfModelKey) => b.points.filter((p) => p.model === k);
    const sel = of(this.chartModel);
    const origin = ms(b.origin_ts);
    const before = b.history.filter((h) => ms(h.ts) <= origin);
    const after = b.history.filter((h) => ms(h.ts) > origin);
    const others = this.compareAll ? this.runModels.filter((k) => k !== this.chartModel) : [];
    this.btFan = fanChart({
      history: before.map((h) => ({ x: ms(h.ts), y: h.price })),
      history5: this.show5min ? b.history_5min.map((h) => ({ x: ms(h.ts), y: h.price })) : [],
      model: this.chartModel,
      forecast: sel.map((p) => ({ x: ms(p.target_ts), p10: p.p10, p50: p.p50, p90: p.p90, mean: p.mean })),
      overlays: others.map((k) => ({ model: k, points: of(k).map((p) => ({ x: ms(p.target_ts), y: p.p50 })) })),
      actualAfter: after.map((h) => ({ x: ms(h.ts), y: h.price })),
      originMs: origin + 30 * 60 * 1000,
      bands: this.forecast?.bands ?? [],
      showMean: this.showMean
    });
    this.btScores = this.runModels
      .map((k) => {
        const pts = of(k).filter((p) => p.actual !== null && p.p50 !== null);
        const mae = pts.reduce((s, p) => s + Math.abs((p.actual ?? 0) - (p.p50 ?? 0)), 0) / Math.max(pts.length, 1);
        const cover = (100 * pts.filter((p) => (p.actual ?? 0) >= (p.p10 ?? 0) && (p.actual ?? 0) <= (p.p90 ?? 0)).length) / Math.max(pts.length, 1);
        return { model: k, mae, cover, n: pts.length };
      })
      .sort((a, b) => a.mae - b.mae);
  }

  rebuild(): void {
    this.buildLive();
    this.buildBacktest();
  }

  num(v: number | null | undefined, d = 1): string {
    return typeof v === 'number' && Number.isFinite(v) ? v.toFixed(d) : '—';
  }

  pct(v: number | null | undefined, d = 1): string {
    return typeof v === 'number' && Number.isFinite(v) ? `${(v * 100).toFixed(d)} %` : '—';
  }

  originTime(): string {
    return this.forecast ? plantLabel(ms(this.forecast.origin_ts) + 3600 * 1000) : '';
  }
}
