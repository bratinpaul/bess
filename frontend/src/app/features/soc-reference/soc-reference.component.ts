import { CommonModule } from '@angular/common';
import { Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { TooltipItem } from 'chart.js';

import { SocMethod, SocRefOptions, SocReference, SocReferenceValues } from '../../core/models/soc-reference.model';
import { SocReferenceService } from '../../core/services/soc-reference.service';
import { AnyConfig, axis, legend, ms, plantLabel, tooltip } from '../ml/price-forecast-shared/pf-charts';
import { ChartCanvasComponent } from '../telemetry/graphs/chart-canvas.component';
import { TableColumn, TableRow } from '../telemetry/table/table-column';
import { TelemetryTableComponent } from '../telemetry/table/telemetry-table.component';

const METHOD_LABELS: Record<SocMethod, string> = {
  FULL_CHARGE: 'Full charge',
  FULL_DISCHARGE: 'Full discharge',
  LAB_RPT: 'Lab RPT',
  REST_OCV: 'Rest OCV'
};
const METHOD_COLORS: Record<SocMethod, string> = {
  FULL_CHARGE: '#12a37f',
  FULL_DISCHARGE: '#e5484d',
  LAB_RPT: '#7c5cdb',
  REST_OCV: '#2f6fed'
};
const DAY = 86400e3;

const COLUMNS: TableColumn[] = [
  { key: 'system_name', label: 'System', kind: 'text', group: 'Key', locked: true },
  { key: 'ts', label: 'Time (plant)', kind: 'timestamp', group: 'Key', locked: true },
  { key: 'soc_true_pct', label: 'True SOC (%)', kind: 'number', group: 'Reference', locked: true },
  { key: 'method_label', label: 'Method', kind: 'text', group: 'Reference', locked: true },
  { key: 'note', label: 'Note', kind: 'text', group: 'Reference', locked: true },
  { key: 'mode_code', label: 'BMS Mode', kind: 'text', group: 'Telemetry', locked: true },
  { key: 'bms_soc_pct', label: 'BMS SOC (%)', kind: 'number', group: 'Telemetry', locked: true },
  { key: 'error_vs_bms', label: 'Error vs BMS (pp)', kind: 'number', group: 'Telemetry', locked: true },
  { key: 'coulomb_soc_pct', label: 'Coulomb SOC (%)', kind: 'number', group: 'Telemetry', locked: true },
  { key: 'error_vs_coulomb', label: 'Error vs Coulomb (pp)', kind: 'number', group: 'Telemetry', locked: true }
];

interface EditState {
  row: SocReference;
  values: SocReferenceValues;
}

/** Core -> Reference -> SOC Reference: the independent ground-truth SOC per plant battery system and moment
 *  (battery_master.soc_reference) - rest-OCV / full-charge / lab anchors the SOC estimators are scored against - with
 *  the BMS and coulomb-counted SOC at those moments; view, edit and delete. */
@Component({
  selector: 'app-soc-reference',
  standalone: true,
  imports: [CommonModule, FormsModule, ChartCanvasComponent, TelemetryTableComponent],
  templateUrl: './soc-reference.component.html',
  styleUrls: ['../calendar/calendar.component.scss', '../aging-snapshot/aging-snapshot.component.scss', './soc-reference.component.scss']
})
export class SocReferenceComponent implements OnInit {
  readonly columns = COLUMNS;
  readonly methodLabels = METHOD_LABELS;

  options: SocRefOptions | null = null;
  rows: SocReference[] = [];
  tableRows: TableRow[] = [];
  loading = true;
  error: string | null = null;
  chartCfg?: AnyConfig;
  filterSystem: number | null = null;
  filterMethod = '';
  filterStart = '';
  filterEnd = '';

  edit: EditState | null = null;
  saving = false;
  editError: string | null = null;
  toDelete: SocReference | null = null;
  deleting = false;
  deleteError: string | null = null;

  constructor(private service: SocReferenceService) {}

  ngOnInit(): void {
    this.service.options().subscribe({
      next: (o) => {
        this.options = o;
        this.filterSystem = o.systems.find((s) => s.points > 0)?.system_id ?? null;
        this.fetchRows();
      },
      error: () => {
        this.loading = false;
        this.error = 'Could not load the SOC reference. Is the backend running?';
      }
    });
  }

  get referencedSystems() {
    return (this.options?.systems ?? []).filter((s) => s.points > 0);
  }

  fetchRows(): void {
    this.loading = true;
    this.error = null;
    this.service
      .list({ systemId: this.filterSystem, method: this.filterMethod || undefined, start: this.filterStart || undefined, end: this.filterEnd || undefined })
      .subscribe({
        next: (rows) => {
          this.rows = rows;
          this.tableRows = rows.map(
            (r) => ({ ...r, method_label: r.method ? METHOD_LABELS[r.method] ?? r.method : '—', note: r.note ?? '—' }) as unknown as TableRow
          );
          this.loading = false;
          this.buildChart();
        },
        error: () => {
          this.loading = false;
          this.error = 'Could not load the SOC reference. Is the backend running?';
        }
      });
  }

  clearFilters(): void {
    this.filterMethod = '';
    this.filterStart = this.filterEnd = '';
    this.fetchRows();
  }

  get stats() {
    const r = this.rows;
    const mean = (xs: (number | null)[]) => {
      const v = xs.filter((x): x is number => x !== null).map(Math.abs);
      return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null;
    };
    const byMethod: Record<string, number> = {};
    r.forEach((x) => (byMethod[x.method ?? '—'] = (byMethod[x.method ?? '—'] ?? 0) + 1));
    return {
      points: r.length,
      byMethod: Object.entries(byMethod).map(([m, n]) => ({ m, n, label: METHOD_LABELS[m as SocMethod] ?? m })),
      maeBms: mean(r.map((x) => x.error_vs_bms)),
      maeCoulomb: mean(r.map((x) => x.error_vs_coulomb)),
      withTelemetry: r.filter((x) => x.bms_soc_pct !== null).length
    };
  }

  num(v: number | null | undefined, d = 2): string {
    return typeof v === 'number' && Number.isFinite(v) ? v.toFixed(d) : '—';
  }

  // ---------------------------------------------------------------- chart

  private buildChart(): void {
    if (!this.rows.length) {
      this.chartCfg = undefined;
      return;
    }
    const xs = this.rows.map((r) => ms(r.ts));
    const from = Math.min(...xs) - DAY / 4;
    const to = Math.max(...xs) + DAY / 4;
    const step = Math.max(1, Math.ceil((to - from) / DAY / 15)) * DAY;
    const methods = Array.from(new Set(this.rows.map((r) => r.method))).filter((m): m is SocMethod => !!m);
    const datasets: any[] = methods.map((m) => ({
      label: `True SOC · ${METHOD_LABELS[m]}`,
      type: 'scatter',
      data: this.rows.filter((r) => r.method === m).map((r) => ({ x: ms(r.ts), y: r.soc_true_pct })),
      backgroundColor: METHOD_COLORS[m],
      borderColor: METHOD_COLORS[m],
      pointRadius: 5,
      pointStyle: 'circle'
    }));
    const est = (key: 'bms_soc_pct' | 'coulomb_soc_pct', label: string, style: string, color: string) => {
      const data = this.rows.filter((r) => r[key] !== null).map((r) => ({ x: ms(r.ts), y: r[key] }));
      if (data.length) {
        datasets.push({ label, type: 'scatter', data, backgroundColor: '#ffffff', borderColor: color, borderWidth: 1.6, pointRadius: 6, pointStyle: style });
      }
    };
    est('bms_soc_pct', 'BMS SOC at that moment', 'rectRot', '#1e232a');
    est('coulomb_soc_pct', 'Coulomb SOC at that moment', 'triangle', '#e8830c');
    this.chartCfg = {
      type: 'scatter',
      data: { datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        plugins: {
          legend: legend(),
          tooltip: {
            ...tooltip,
            callbacks: {
              title: (items: TooltipItem<'scatter'>[]) => (items[0] ? plantLabel(items[0].parsed.x as number) : ''),
              label: (ctx: TooltipItem<'scatter'>) => `${ctx.dataset.label}: ${(ctx.parsed.y as number).toFixed(2)} %`
            }
          }
        },
        scales: {
          x: axis(undefined, {
            type: 'linear',
            min: from,
            max: to,
            // daily-ish ticks built here (never stepSize on an epoch axis)
            afterBuildTicks: (scale: any) => {
              const ticks = [];
              for (let t = Math.ceil(from / DAY) * DAY; t <= to && ticks.length < 40; t += step) {
                ticks.push({ value: t });
              }
              scale.ticks = ticks;
            },
            ticks: { maxRotation: 0, autoSkip: true, callback: (v: number | string) => plantLabel(Number(v)).slice(0, 6) }
          }),
          y: axis('SOC (%)', { min: 0, max: 100 })
        }
      }
    } as AnyConfig;
  }

  // ---------------------------------------------------------------- edit / delete

  private find(row: TableRow): SocReference | undefined {
    const r = row as unknown as SocReference;
    return this.rows.find((x) => x.system_id === r.system_id && x.ts === r.ts);
  }

  openEdit(row: TableRow): void {
    const r = this.find(row);
    if (!r) {
      return;
    }
    this.editError = null;
    this.edit = { row: r, values: { soc_true_pct: r.soc_true_pct, method: r.method, note: r.note ?? '' } };
  }

  get editProblem(): string | null {
    const v = this.edit?.values.soc_true_pct as unknown;
    if (v === null || v === undefined || v === '') {
      return 'Enter the true SOC';
    }
    const n = Number(v);
    return Number.isFinite(n) && n >= 0 && n <= 100 ? null : 'True SOC must be between 0 and 100 %';
  }

  /** The edited value against the estimates at that moment. */
  get editErrors(): { bms: number | null; coulomb: number | null } | null {
    const e = this.edit;
    if (!e || this.editProblem) {
      return null;
    }
    const t = Number(e.values.soc_true_pct);
    return {
      bms: e.row.bms_soc_pct !== null ? t - e.row.bms_soc_pct : null,
      coulomb: e.row.coulomb_soc_pct !== null ? t - e.row.coulomb_soc_pct : null
    };
  }

  save(): void {
    const e = this.edit;
    if (!e || this.editProblem) {
      return;
    }
    this.saving = true;
    this.editError = null;
    this.service
      .update(e.row, { soc_true_pct: Number(e.values.soc_true_pct), method: e.values.method || null, note: (e.values.note ?? '').trim() || null })
      .subscribe({
        next: () => {
          this.saving = false;
          this.edit = null;
          this.fetchRows();
        },
        error: (err) => {
          this.saving = false;
          const d = err?.error?.detail;
          this.editError = Array.isArray(d) ? d.map((x: { loc: string[]; msg: string }) => `${x.loc?.[x.loc.length - 1]}: ${x.msg}`).join('; ') : d || 'Saving failed.';
        }
      });
  }

  confirmDelete(row: TableRow): void {
    this.deleteError = null;
    this.toDelete = this.find(row) ?? null;
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
        this.fetchRows();
      },
      error: (err) => {
        this.deleting = false;
        this.deleteError = err?.error?.detail || 'Deleting failed.';
      }
    });
  }

  plantTime(iso: string): string {
    return plantLabel(ms(iso));
  }
}
