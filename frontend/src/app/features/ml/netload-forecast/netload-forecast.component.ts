import { CommonModule } from '@angular/common';
import { Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';

import {
  NfBacktest,
  NfForecast,
  NfModelKey,
  NfModelOption,
  NfPeak,
  NfRegressorKey,
  NfUnit
} from '../../../core/models/netload-forecast.model';
import { NetloadForecastService } from '../../../core/services/netload-forecast.service';
import { ChartCanvasComponent } from '../../telemetry/graphs/chart-canvas.component';
import { AnyConfig, NF_COLORS, NF_LABELS, NF_ORDER, hhmm, inputChart, ms, netloadFan, pct, plantLabel } from '../netload-forecast-shared/nf-charts';

interface PeakCard {
  date: string;
  label: string;
  lead: number | null;
  peak: NfPeak;
  clf: NfPeak | null;
  margin: number | null;
  reserve: number | null;
  status: 'breach' | 'watch' | 'clear';
}

interface BtPeakRow {
  date: string;
  model: NfModelKey;
  p50: number | null;
  p10: number | null;
  p90: number | null;
  prob: number | null;
  peakTs: string | null;
  actual: number | null;
  actualTs: string | null;
  hit: boolean | null;
}

/** Insights -> Forecasting -> Demand / Peak Forecast: the next 48 h net-load forecast per metering point (fan chart,
 *  weather inputs), the daily billing-peak outlook against the threshold, and the backtests of a run. */
@Component({
  selector: 'app-netload-forecast',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink, ChartCanvasComponent],
  templateUrl: './netload-forecast.component.html',
  styleUrls: ['../soh-estimator/soh-estimator.component.scss', '../price-forecast/price-forecast.component.scss', './netload-forecast.component.scss']
})
export class NetloadForecastComponent implements OnInit {
  readonly colors = NF_COLORS;
  readonly labels = NF_LABELS;
  readonly pct = pct;
  readonly hhmm = hhmm;

  models: NfModelOption[] = [];
  modelsLoaded = false;
  modelsError: string | null = null;
  modelKey = 'active';
  units: NfUnit[] = [];
  mpId: number | null = null;
  tab: 'live' | 'backtest' = 'live';
  threshold: number | null = null;

  chartModel: NfRegressorKey = 'lightgbm';
  compareAll = false;
  showGross = true;

  forecast: NfForecast | null = null;
  loading = false;
  error: string | null = null;
  fan?: AnyConfig;
  tempChart?: AnyConfig;
  ghiChart?: AnyConfig;
  cards: PeakCard[] = [];

  origins: string[] = [];
  originIdx = 0;
  backtest: NfBacktest | null = null;
  btError: string | null = null;
  btFan?: AnyConfig;
  btScores: { model: NfRegressorKey; mae: number; cover: number; n: number }[] = [];
  btPeaks: BtPeakRow[] = [];

  constructor(private service: NetloadForecastService, private route: ActivatedRoute, private router: Router) {}

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
          const mp = Number(q.get('mp'));
          this.mpId = run.mp_ids.includes(mp) ? mp : run.mp_ids[0];
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

  get run(): NfModelOption | undefined {
    return this.modelKey === 'active' ? this.models[0] : this.models.find((m) => String(m.run_id) === this.modelKey);
  }

  get runModels(): NfRegressorKey[] {
    return NF_ORDER.filter((k) => this.run?.models.includes(k));
  }

  optionLabel(m: NfModelOption): string {
    const best = m.best_model ? `${NF_LABELS[m.best_model]} MAE ${m.metrics?.[m.best_model]?.mae?.toFixed(0) ?? '—'} kW` : '';
    return `#${m.run_id}${m.run_name ? ' ' + m.run_name : ''}${m.is_default ? ' (default)' : ''} · ${best}`;
  }

  unitLabel(id: number): string {
    const u = this.units.find((x) => x.mp_id === id);
    return u ? `${u.mp_code} · ${u.site_name ?? 'site ' + u.site_id}` : `Metering point ${id}`;
  }

  selectModel(key: string): void {
    this.modelKey = key;
    const run = this.run;
    if (run && (!this.mpId || !run.mp_ids.includes(this.mpId))) {
      this.mpId = run.mp_ids[0];
    }
    if (run && !run.models.includes(this.chartModel)) {
      this.chartModel = run.best_model ?? (run.models[0] as NfRegressorKey);
    }
    this.threshold = null;
    this.load();
  }

  selectMp(id: number): void {
    this.mpId = id;
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
      queryParams: { model: this.modelKey === 'active' ? null : this.modelKey, mp: this.mpId },
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
    if (!this.mpId) {
      return;
    }
    this.loading = true;
    this.error = null;
    this.service.forecast(this.mpId, this.modelKey, this.threshold, 48).subscribe({
      next: (f) => {
        this.forecast = f;
        this.loading = false;
        if (this.threshold === null) {
          this.threshold = f.trained_threshold_kw;
        }
        if (!f.forecasts[this.chartModel]) {
          this.chartModel = f.best_model ?? (Object.keys(f.forecasts)[0] as NfRegressorKey);
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

  applyThreshold(): void {
    if (this.threshold && this.threshold > 0) {
      this.loadForecast();
      if (this.backtest) {
        this.buildBacktest();
      }
    }
  }

  resetThreshold(): void {
    this.threshold = this.forecast?.trained_threshold_kw ?? null;
    this.applyThreshold();
  }

  setChartModel(k: NfRegressorKey): void {
    this.chartModel = k;
    this.buildLive();
    this.buildBacktest();
  }

  get thresholdKw(): number {
    return this.forecast?.threshold_kw ?? this.threshold ?? 0;
  }

  buildLive(): void {
    const f = this.forecast;
    const pts = f?.forecasts[this.chartModel];
    if (!f || !pts) {
      this.fan = undefined;
      this.cards = [];
      return;
    }
    const peaks = f.peaks[this.chartModel] ?? [];
    const others = this.compareAll ? this.runModels.filter((k) => k !== this.chartModel && f.forecasts[k]) : [];
    this.fan = netloadFan({
      history: f.history.map((h) => ({ x: ms(h.ts), net: h.net, gross: h.gross, gen: h.gen })),
      model: this.chartModel,
      forecast: pts.map((p) => ({ x: ms(p.target_ts), p10: p.p10, p50: p.p50, p90: p.p90 })),
      overlays: others.map((k) => ({ model: k, points: (f.forecasts[k] ?? []).map((p) => ({ x: ms(p.target_ts), y: p.p50 })) })),
      peaks: peaks.filter((p) => p.peak_ts && p.p50 !== null).map((p) => ({ x: ms(p.peak_ts!), y: p.p50!, label: `Peak ${p.target_date}` })),
      originMs: ms(f.origin_ts),
      window: f.window,
      threshold: f.threshold_kw,
      showGross: this.showGross
    });
    const xs = f.inputs.map((i) => ms(i.ts));
    const from = Math.min(...xs);
    const to = Math.max(...xs);
    this.tempChart = inputChart(f.inputs.map((i) => ({ x: ms(i.ts), y: i.temp_fc, fc: i.from_forecast })), 'Temperature', '°C', '#d62828', from, to, f.window);
    this.ghiChart = inputChart(f.inputs.map((i) => ({ x: ms(i.ts), y: i.ghi_fc, fc: i.from_forecast })), 'GHI', 'W/m²', '#d4a017', from, to, f.window);
    const clf = f.peaks.peak_classifier ?? [];
    const T = f.threshold_kw;
    this.cards = peaks.map((p) => {
      const prob = p.prob_exceed ?? 0;
      return {
        date: p.target_date,
        label: new Date(p.target_date + 'T00:00:00').toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'short' }),
        lead: p.lead_h,
        peak: p,
        clf: clf.find((c) => c.target_date === p.target_date) ?? null,
        margin: p.p50 !== null && p.p50 !== undefined ? p.p50 - T : null,
        reserve: p.p90 !== null && p.p90 !== undefined ? Math.max(0, p.p90 - T) : null,
        status: prob >= 0.5 ? 'breach' : prob >= 0.2 ? 'watch' : 'clear'
      };
    });
  }

  get modelScore() {
    return this.run?.metrics?.[this.chartModel] ?? null;
  }

  get inputsFromForecast(): number {
    const i = this.forecast?.inputs ?? [];
    return i.length ? i.filter((x) => x.from_forecast).length / i.length : 0;
  }

  get stale(): boolean {
    return (this.forecast?.data_age_hours ?? 0) > 2;
  }

  ageText(h: number | null): string {
    if (h === null) {
      return '';
    }
    return h < 48 ? `${h.toFixed(0)} h` : `${(h / 24).toFixed(0)} days`;
  }

  dayType(date: string): string {
    const workday = this.forecast?.inputs.find((i) => plantLabel(ms(i.ts)).startsWith(date.slice(8, 10)))?.workday;
    return workday === undefined ? '' : workday ? 'workday' : 'weekend / holiday';
  }

  get recentMax(): number | null {
    const p = (this.forecast?.recent_peaks ?? []).map((x) => x.peak).filter((v): v is number => v !== null);
    return p.length ? Math.max(...p) : null;
  }

  // ---------------------------------------------------------------- backtest

  loadOrigins(): void {
    const run = this.run;
    if (!run || !this.mpId) {
      return;
    }
    this.service.origins(run.run_id, this.mpId).subscribe({
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
    if (!run || !this.mpId || !o) {
      return;
    }
    this.btError = null;
    this.service.backtest(run.run_id, this.mpId, o).subscribe({
      next: (b) => {
        this.backtest = b;
        this.buildBacktest();
      },
      error: (err) => (this.btError = err?.error?.detail || 'Could not load the backtest.')
    });
  }

  buildBacktest(): void {
    const b = this.backtest;
    if (!b) {
      this.btFan = undefined;
      return;
    }
    const of = (k: NfRegressorKey) => b.points.filter((p) => p.model === k);
    const sel = of(this.chartModel);
    const origin = ms(b.origin_ts);
    const before = b.history.filter((h) => ms(h.ts) <= origin);
    const after = b.history.filter((h) => ms(h.ts) > origin);
    const others = this.compareAll ? this.runModels.filter((k) => k !== this.chartModel) : [];
    const T = b.peaks[0]?.threshold_kw ?? this.run?.peak_threshold_kw ?? 0;
    const window = this.forecast?.window ?? [17, 22];
    this.btFan = netloadFan({
      history: before.map((h) => ({ x: ms(h.ts), net: h.net, gross: h.gross, gen: h.gen })),
      model: this.chartModel,
      forecast: sel.map((p) => ({ x: ms(p.target_ts), p10: p.p10, p50: p.p50, p90: p.p90 })),
      overlays: others.map((k) => ({ model: k, points: of(k).map((p) => ({ x: ms(p.target_ts), y: p.p50 })) })),
      actualAfter: after.map((h) => ({ x: ms(h.ts), y: h.net })),
      peaks: b.peaks
        .filter((p) => p.model === this.chartModel && p.peak_ts && p.p50 !== null)
        .map((p) => ({ x: ms(p.peak_ts!), y: p.p50!, label: `Peak ${p.target_date}` })),
      originMs: origin,
      window,
      threshold: T,
      showGross: this.showGross
    });
    this.btScores = this.runModels
      .map((k) => {
        const pts = of(k).filter((p) => p.actual !== null && p.p50 !== null);
        const mae = pts.reduce((s, p) => s + Math.abs((p.actual ?? 0) - (p.p50 ?? 0)), 0) / Math.max(pts.length, 1);
        const cover = (100 * pts.filter((p) => (p.actual ?? 0) >= (p.p10 ?? 0) && (p.actual ?? 0) <= (p.p90 ?? 0)).length) / Math.max(pts.length, 1);
        return { model: k, mae, cover, n: pts.length };
      })
      .sort((a, b2) => a.mae - b2.mae);
    const order: NfModelKey[] = [...this.runModels, 'peak_classifier'];
    this.btPeaks = b.peaks
      .map((p) => ({
        date: p.target_date,
        model: p.model,
        p50: p.p50 ?? null,
        p10: p.p10 ?? null,
        p90: p.p90 ?? null,
        prob: p.prob_exceed,
        peakTs: p.peak_ts ?? null,
        actual: p.actual ?? null,
        actualTs: p.actual_ts ?? null,
        hit: p.actual === null || p.actual === undefined || p.prob_exceed === null ? null : p.prob_exceed >= 0.5 === p.actual > p.threshold_kw
      }))
      .sort((a, c) => (a.date === c.date ? order.indexOf(a.model) - order.indexOf(c.model) : a.date < c.date ? -1 : 1));
  }

  get btThreshold(): number | null {
    return this.backtest?.peaks[0]?.threshold_kw ?? null;
  }

  rebuild(): void {
    this.buildLive();
    this.buildBacktest();
  }

  num(v: number | null | undefined, d = 0): string {
    return typeof v === 'number' && Number.isFinite(v) ? v.toFixed(d) : '—';
  }

  signed(v: number | null | undefined): string {
    return typeof v === 'number' && Number.isFinite(v) ? `${v > 0 ? '+' : ''}${v.toFixed(0)}` : '—';
  }
}
