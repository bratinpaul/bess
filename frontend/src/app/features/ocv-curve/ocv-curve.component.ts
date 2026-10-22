import { CommonModule } from '@angular/common';
import { Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { TooltipItem } from 'chart.js';

import { OcvCurveSummary, OcvDirection, OcvOptions, OcvPoint } from '../../core/models/ocv-curve.model';
import { OcvCurveService } from '../../core/services/ocv-curve.service';
import { AnyConfig, axis, legend, tooltip } from '../ml/price-forecast-shared/pf-charts';
import { ChartCanvasComponent } from '../telemetry/graphs/chart-canvas.component';
import { TableColumn, TableRow } from '../telemetry/table/table-column';
import { TelemetryTableComponent } from '../telemetry/table/telemetry-table.component';

/* direction = colour, temperature = dash */
const DIR_COLORS: Record<OcvDirection, string> = { CHARGE: '#e8830c', DISCHARGE: '#2f6fed', MEAN: '#1e232a' };
const DIR_LABELS: Record<OcvDirection, string> = { CHARGE: 'Charge', DISCHARGE: 'Discharge', MEAN: 'Mean' };
const TEMP_DASH = (t: number, temps: number[]): number[] => {
  const i = temps.indexOf(t);
  return [[6, 3], [], [2, 3], [10, 3, 2, 3]][i % 4] ?? [];
};

const COLUMNS: TableColumn[] = [
  { key: 'chemistry', label: 'Chemistry', kind: 'text', group: 'Key', locked: true },
  { key: 'direction_label', label: 'Direction', kind: 'text', group: 'Key', locked: true },
  { key: 'temp_c', label: 'Temp (°C)', kind: 'number', group: 'Key', locked: true },
  { key: 'soc_pct', label: 'SOC (%)', kind: 'number', group: 'Key', locked: true },
  { key: 'ocv_v', label: 'OCV (V / cell)', kind: 'number', group: 'Value', locked: true },
  { key: 'step_mv', label: 'Δ from previous SOC (mV)', kind: 'number', group: 'Value', locked: true }
];

interface EditState {
  point: OcvPoint;
  ocv: number | null;
  prev: OcvPoint | null;
  next: OcvPoint | null;
}

/** Core -> Reference -> OCV Curve: per-cell open-circuit voltage vs SOC by chemistry, direction (charge / discharge
 *  hysteresis or their mean) and temperature (battery_master.ocv_curve) - the curves, the hysteresis, and the points
 *  to view, edit and delete. */
@Component({
  selector: 'app-ocv-curve',
  standalone: true,
  imports: [CommonModule, FormsModule, ChartCanvasComponent, TelemetryTableComponent],
  templateUrl: './ocv-curve.component.html',
  styleUrls: ['../calendar/calendar.component.scss', '../aging-snapshot/aging-snapshot.component.scss', './ocv-curve.component.scss']
})
export class OcvCurveComponent implements OnInit {
  readonly columns = COLUMNS;
  readonly dirLabels = DIR_LABELS;
  readonly dirColors = DIR_COLORS;

  options: OcvOptions | null = null;
  chemistry = '';
  directions = new Set<OcvDirection>(['CHARGE', 'DISCHARGE', 'MEAN']);
  temps = new Set<number>();
  curves: OcvCurveSummary[] = [];
  points: OcvPoint[] = [];
  tableRows: TableRow[] = [];
  loading = true;
  error: string | null = null;
  curveCfg?: AnyConfig;
  hystCfg?: AnyConfig;

  edit: EditState | null = null;
  saving = false;
  editError: string | null = null;
  toDelete: OcvPoint | null = null;
  deleting = false;
  deleteError: string | null = null;

  constructor(private service: OcvCurveService) {}

  ngOnInit(): void {
    this.service.options().subscribe({
      next: (o) => {
        this.options = o;
        this.chemistry = o.chemistries[0] ?? '';
        this.temps = new Set(o.temperatures);
        this.load();
      },
      error: () => {
        this.loading = false;
        this.error = 'Could not load the OCV curves. Is the backend running?';
      }
    });
  }

  // ---------------------------------------------------------------- data

  load(): void {
    if (!this.chemistry) {
      this.loading = false;
      return;
    }
    this.loading = true;
    this.error = null;
    this.service.curves({ chemistry: this.chemistry }).subscribe({
      next: (c) => {
        this.curves = c;
        this.service.list({ chemistry: this.chemistry }).subscribe({
          next: (p) => {
            this.points = p;
            this.loading = false;
            this.refresh();
          },
          error: () => this.fail()
        });
      },
      error: () => this.fail()
    });
  }

  private fail(): void {
    this.loading = false;
    this.error = 'Could not load the OCV curves. Is the backend running?';
  }

  get temperatures(): number[] {
    return this.options?.temperatures ?? [];
  }

  get shownCurves(): OcvCurveSummary[] {
    return this.curves.filter((c) => this.directions.has(c.direction) && this.temps.has(c.temp_c));
  }

  get stats() {
    const c = this.curves;
    const all = c.flatMap((x) => x.ocv);
    return {
      curves: c.length,
      points: this.points.length,
      min: all.length ? Math.min(...all) : null,
      max: all.length ? Math.max(...all) : null,
      nonMonotonic: c.filter((x) => !x.monotonic).length
    };
  }

  toggleDir(d: OcvDirection): void {
    const s = new Set(this.directions);
    s.has(d) ? s.delete(d) : s.add(d);
    this.directions = s;
    this.refresh();
  }

  toggleTemp(t: number): void {
    const s = new Set(this.temps);
    s.has(t) ? s.delete(t) : s.add(t);
    this.temps = s;
    this.refresh();
  }

  private refresh(): void {
    const shown = this.points.filter((p) => this.directions.has(p.direction) && this.temps.has(p.temp_c));
    const prevOf = new Map<string, number>();
    this.tableRows = shown.map((p) => {
      const k = `${p.direction}|${p.temp_c}`;
      const prev = prevOf.get(k);
      prevOf.set(k, p.ocv_v);
      return {
        ...p,
        direction_label: DIR_LABELS[p.direction] ?? p.direction,
        step_mv: prev === undefined ? null : Math.round((p.ocv_v - prev) * 10000) / 10
      } as unknown as TableRow;
    });
    this.buildCharts();
  }

  // ---------------------------------------------------------------- charts

  private buildCharts(): void {
    const temps = this.temperatures;
    const curves = this.shownCurves;
    this.curveCfg = curves.length
      ? ({
          type: 'line',
          data: {
            datasets: curves.map((c) => ({
              label: `${DIR_LABELS[c.direction]} · ${c.temp_c} °C`,
              data: c.soc.map((s, i) => ({ x: s, y: c.ocv[i] })),
              borderColor: DIR_COLORS[c.direction],
              backgroundColor: DIR_COLORS[c.direction],
              borderDash: TEMP_DASH(c.temp_c, temps),
              borderWidth: c.direction === 'MEAN' ? 2.2 : 1.6,
              pointRadius: 2.5,
              tension: 0.15
            }))
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            interaction: { mode: 'nearest', axis: 'x', intersect: false },
            plugins: {
              legend: legend(),
              tooltip: {
                ...tooltip,
                callbacks: {
                  title: (items: TooltipItem<'line'>[]) => (items[0] ? `SOC ${items[0].parsed.x} %` : ''),
                  label: (ctx: TooltipItem<'line'>) => `${ctx.dataset.label}: ${(ctx.parsed.y as number).toFixed(4)} V`
                }
              }
            },
            scales: {
              x: axis('SOC (%)', { type: 'linear', min: 0, max: 100 }),
              y: axis('OCV (V per cell)')
            }
          }
        } as AnyConfig)
      : undefined;
    // hysteresis: charge - discharge at each temperature
    const hyst = temps
      .filter((t) => this.temps.has(t))
      .map((t) => {
        const ch = this.curves.find((c) => c.direction === 'CHARGE' && c.temp_c === t);
        const dis = this.curves.find((c) => c.direction === 'DISCHARGE' && c.temp_c === t);
        if (!ch || !dis) {
          return null;
        }
        const pts = ch.soc
          .map((s, i) => {
            const j = dis.soc.indexOf(s);
            return j >= 0 ? { x: s, y: Math.round((ch.ocv[i] - dis.ocv[j]) * 10000) / 10 } : null;
          })
          .filter((p): p is { x: number; y: number } => p !== null);
        return { t, pts };
      })
      .filter((h): h is { t: number; pts: { x: number; y: number }[] } => h !== null);
    this.hystCfg = hyst.length
      ? ({
          type: 'line',
          data: {
            datasets: hyst.map((h) => ({
              label: `${h.t} °C`,
              data: h.pts,
              borderColor: '#7c5cdb',
              backgroundColor: '#7c5cdb',
              borderDash: TEMP_DASH(h.t, temps),
              borderWidth: 1.8,
              pointRadius: 2.5
            }))
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            interaction: { mode: 'nearest', axis: 'x', intersect: false },
            plugins: {
              legend: legend(),
              tooltip: {
                ...tooltip,
                callbacks: {
                  title: (items: TooltipItem<'line'>[]) => (items[0] ? `SOC ${items[0].parsed.x} %` : ''),
                  label: (ctx: TooltipItem<'line'>) => `${ctx.dataset.label}: ${(ctx.parsed.y as number).toFixed(1)} mV`
                }
              }
            },
            scales: {
              x: axis('SOC (%)', { type: 'linear', min: 0, max: 100 }),
              y: axis('Charge − discharge (mV)', { beginAtZero: true })
            }
          }
        } as AnyConfig)
      : undefined;
  }

  // ---------------------------------------------------------------- edit / delete

  private neighbours(p: OcvPoint): { prev: OcvPoint | null; next: OcvPoint | null } {
    const same = this.points
      .filter((x) => x.chemistry === p.chemistry && x.direction === p.direction && x.temp_c === p.temp_c)
      .sort((a, b) => a.soc_pct - b.soc_pct);
    const i = same.findIndex((x) => x.soc_pct === p.soc_pct);
    return { prev: i > 0 ? same[i - 1] : null, next: i >= 0 && i < same.length - 1 ? same[i + 1] : null };
  }

  private toPoint(row: TableRow): OcvPoint | undefined {
    const r = row as unknown as OcvPoint;
    return this.points.find((p) => p.chemistry === r.chemistry && p.direction === r.direction && p.temp_c === r.temp_c && p.soc_pct === r.soc_pct);
  }

  openEdit(row: TableRow): void {
    const p = this.toPoint(row);
    if (!p) {
      return;
    }
    this.editError = null;
    this.edit = { point: p, ocv: p.ocv_v, ...this.neighbours(p) };
  }

  get editProblem(): string | null {
    const v = this.edit?.ocv as unknown;
    if (v === null || v === undefined || v === '') {
      return 'Enter the OCV';
    }
    const n = Number(v);
    if (!Number.isFinite(n) || n <= 0 || n > 6) {
      return 'OCV must be above 0 and at most 6 V (a per-cell voltage)';
    }
    return null;
  }

  /** OCV should rise with SOC along a curve: a value below the previous point or above the next one is suspicious. */
  get editWarning(): string | null {
    const e = this.edit;
    if (!e || this.editProblem) {
      return null;
    }
    const n = Number(e.ocv);
    if (e.prev && n < e.prev.ocv_v) {
      return `Below the ${e.prev.soc_pct} % point (${e.prev.ocv_v.toFixed(4)} V) — the curve would no longer rise with SOC`;
    }
    if (e.next && n > e.next.ocv_v) {
      return `Above the ${e.next.soc_pct} % point (${e.next.ocv_v.toFixed(4)} V) — the curve would no longer rise with SOC`;
    }
    return null;
  }

  save(): void {
    const e = this.edit;
    if (!e || this.editProblem) {
      return;
    }
    this.saving = true;
    this.editError = null;
    this.service.update(e.point, Number(e.ocv)).subscribe({
      next: () => {
        this.saving = false;
        this.edit = null;
        this.load();
      },
      error: (err) => {
        this.saving = false;
        const d = err?.error?.detail;
        this.editError = Array.isArray(d) ? d.map((x: { msg: string }) => x.msg).join('; ') : d || 'Saving failed.';
      }
    });
  }

  confirmDelete(row: TableRow): void {
    this.deleteError = null;
    this.toDelete = this.toPoint(row) ?? null;
  }

  deleteConfirmed(): void {
    const t = this.toDelete;
    if (!t) {
      return;
    }
    this.deleting = true;
    this.service.delete(t).subscribe({
      next: () => {
        this.deleting = false;
        this.toDelete = null;
        this.load();
      },
      error: (err) => {
        this.deleting = false;
        this.deleteError = err?.error?.detail || 'Deleting failed.';
      }
    });
  }
}
