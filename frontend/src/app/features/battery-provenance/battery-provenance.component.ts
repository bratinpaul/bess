import { CommonModule } from '@angular/common';
import { Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { BatteryProvenance, BatteryProvenanceValues, ProvenanceOptions } from '../../core/models/battery-provenance.model';
import { BatteryProvenanceService } from '../../core/services/battery-provenance.service';
import { ColumnPickerComponent } from '../telemetry/table/column-picker.component';
import { TableColumn, TableRow } from '../telemetry/table/table-column';
import { TelemetryTableComponent } from '../telemetry/table/telemetry-table.component';

const PROV_COLUMNS: TableColumn[] = [
  { key: 'system_code', label: 'System', kind: 'text', group: 'System', locked: true },
  { key: 'commissioned_on', label: 'Commissioned', kind: 'text', group: 'System' },
  { key: 'manufacturer', label: 'Manufacturer', kind: 'text', group: 'Cell' },
  { key: 'cell_model', label: 'Cell Model', kind: 'text', group: 'Cell' },
  { key: 'chemistry', label: 'Chemistry', kind: 'text', group: 'Cell' },
  { key: 'cell_format', label: 'Cell Format', kind: 'text', group: 'Cell' },
  { key: 'batch_lot', label: 'Batch Lot', kind: 'text', group: 'Cell' },
  { key: 'build_date', label: 'Build Date', kind: 'text', group: 'Cell' },
  { key: 'nameplate_kwh', label: 'Nameplate (kWh)', kind: 'number', group: 'Beginning of life' },
  { key: 'bol_capacity_kwh', label: 'BOL Capacity (kWh)', kind: 'number', group: 'Beginning of life' },
  { key: 'bol_resistance_mohm', label: 'BOL Resistance (mΩ)', kind: 'number', group: 'Beginning of life' },
  { key: 'usage_cycles_per_day', label: 'Cycles / Day', kind: 'number', group: 'Duty & climate' },
  { key: 'climate_avg_temp_c', label: 'Climate Avg Temp (°C)', kind: 'number', group: 'Duty & climate' },
  { key: 'eol_label', label: 'EOL Criteria', kind: 'text', group: 'End of life' }
];

const SORTS: { key: string; label: string }[] = [
  { key: 'system_code', label: 'System' },
  { key: 'batch_lot', label: 'Batch lot' },
  { key: 'build_date', label: 'Build date' },
  { key: 'bol_capacity_kwh', label: 'BOL capacity' },
  { key: 'bol_resistance_mohm', label: 'BOL resistance' },
  { key: 'usage_cycles_per_day', label: 'Cycles per day' },
  { key: 'climate_avg_temp_c', label: 'Climate temperature' }
];

interface TextField {
  key: 'manufacturer' | 'cell_model' | 'batch_lot' | 'cell_format';
  label: string;
  list: keyof ProvenanceOptions;
}

interface NumField {
  key: keyof BatteryProvenanceValues;
  label: string;
  step: number;
  min?: number;
  max?: number;
  positive?: boolean;
}

const TEXT_FIELDS: TextField[] = [
  { key: 'manufacturer', label: 'Manufacturer', list: 'manufacturers' },
  { key: 'cell_model', label: 'Cell model', list: 'cell_models' },
  { key: 'cell_format', label: 'Cell format', list: 'cell_formats' },
  { key: 'batch_lot', label: 'Batch lot', list: 'batch_lots' }
];

const NUM_FIELDS: NumField[] = [
  { key: 'nameplate_kwh', label: 'Nameplate (kWh)', step: 1, positive: true },
  { key: 'bol_capacity_kwh', label: 'BOL capacity (kWh)', step: 0.1, positive: true },
  { key: 'bol_resistance_mohm', label: 'BOL resistance (mΩ)', step: 0.001, positive: true },
  { key: 'usage_cycles_per_day', label: 'Cycles per day', step: 0.01, min: 0, max: 50 },
  { key: 'climate_avg_temp_c', label: 'Climate avg temp (°C)', step: 0.1, min: -40, max: 70 }
];

interface EditState {
  row: BatteryProvenance;
  values: BatteryProvenanceValues;
}

/** Core -> Reference -> Battery Provenance: cell provenance, batch and beginning-of-life baseline per RUL fleet
 *  system (battery_master.battery_provenance); view, filter, edit and delete. */
@Component({
  selector: 'app-battery-provenance',
  standalone: true,
  imports: [CommonModule, FormsModule, ColumnPickerComponent, TelemetryTableComponent],
  templateUrl: './battery-provenance.component.html',
  styleUrls: [
    '../calendar/calendar.component.scss',
    '../aging-snapshot/aging-snapshot.component.scss',
    '../lifecycle-event/lifecycle-event.component.scss'
  ]
})
export class BatteryProvenanceComponent implements OnInit {
  readonly allColumns = PROV_COLUMNS;
  readonly defaultColumnKeys = PROV_COLUMNS.map((c) => c.key);
  readonly sorts = SORTS;
  readonly textFields = TEXT_FIELDS;
  readonly numFields = NUM_FIELDS;
  visibleColumns: TableColumn[] = PROV_COLUMNS;

  options: ProvenanceOptions | null = null;
  /** The whole fleet (unfiltered) for the batch summary. */
  fleet: BatteryProvenance[] = [];
  rows: BatteryProvenance[] = [];
  tableRows: TableRow[] = [];
  loading = true;
  error: string | null = null;

  filterChemistry = '';
  filterBatch = '';
  sort = 'system_code';
  order: 'asc' | 'desc' = 'asc';

  edit: EditState | null = null;
  saving = false;
  editError: string | null = null;
  toDelete: BatteryProvenance | null = null;
  deleting = false;
  deleteError: string | null = null;

  constructor(private service: BatteryProvenanceService) {}

  ngOnInit(): void {
    this.loadOptions();
    this.fetchRows();
  }

  /** Filter choices, EOL criteria and the unfiltered fleet (reloaded after an edit or delete). */
  loadOptions(): void {
    this.service.options().subscribe({ next: (o) => (this.options = o), error: () => (this.options = null) });
    this.service.list({}).subscribe({ next: (all) => (this.fleet = all), error: () => (this.fleet = []) });
  }

  // ---------------------------------------------------------------- summary

  /** Systems per batch lot over the whole fleet. */
  get batches(): { lot: string; n: number; bolAvg: number | null }[] {
    const by = new Map<string, BatteryProvenance[]>();
    for (const r of this.fleet) {
      const k = r.batch_lot ?? '—';
      by.set(k, [...(by.get(k) ?? []), r]);
    }
    return Array.from(by.entries())
      .sort((a, b) => a[0].localeCompare(b[0]))
      .map(([lot, rs]) => {
        const caps = rs.map((r) => r.bol_capacity_kwh).filter((v): v is number => v !== null);
        return { lot, n: rs.length, bolAvg: caps.length ? caps.reduce((a, v) => a + v, 0) / caps.length : null };
      });
  }

  selectBatch(lot: string): void {
    this.filterBatch = this.filterBatch === lot ? '' : lot;
    this.fetchRows();
  }

  // ---------------------------------------------------------------- table

  fetchRows(): void {
    this.loading = true;
    this.error = null;
    this.service
      .list({ chemistry: this.filterChemistry || undefined, batchLot: this.filterBatch || undefined, sort: this.sort, order: this.order })
      .subscribe({
        next: (rows) => {
          this.rows = rows;
          this.tableRows = rows.map(
            (r) =>
              ({
                ...r,
                commissioned_on: r.commissioned_on ?? '—',
                build_date: r.build_date ?? '—',
                eol_label:
                  r.soh_eol_pct !== null
                    ? `SOH < ${r.soh_eol_pct} %${r.resistance_eol_pct !== null ? ` or R > ${r.resistance_eol_pct} % of BOL` : ''}`
                    : 'not defined'
              }) as unknown as TableRow
          );
          this.loading = false;
        },
        error: () => {
          this.error = 'Could not load the battery provenance. Is the backend running?';
          this.loading = false;
        }
      });
  }

  applyFilters(): void {
    this.fetchRows();
  }

  clearFilters(): void {
    this.filterChemistry = '';
    this.filterBatch = '';
    this.fetchRows();
  }

  toggleOrder(): void {
    this.order = this.order === 'asc' ? 'desc' : 'asc';
    this.fetchRows();
  }

  num(v: number | null | undefined, d = 1): string {
    return typeof v === 'number' && Number.isFinite(v) ? v.toFixed(d) : '—';
  }

  // ---------------------------------------------------------------- edit / delete

  openEdit(row: TableRow): void {
    const r = this.rows.find((x) => x.system_id === (row as unknown as BatteryProvenance).system_id);
    if (!r) {
      return;
    }
    this.editError = null;
    this.edit = {
      row: r,
      values: {
        manufacturer: r.manufacturer ?? '',
        cell_model: r.cell_model ?? '',
        chemistry: r.chemistry,
        batch_lot: r.batch_lot ?? '',
        cell_format: r.cell_format ?? '',
        build_date: r.build_date ?? '',
        nameplate_kwh: r.nameplate_kwh,
        bol_capacity_kwh: r.bol_capacity_kwh,
        bol_resistance_mohm: r.bol_resistance_mohm,
        usage_cycles_per_day: r.usage_cycles_per_day,
        climate_avg_temp_c: r.climate_avg_temp_c
      }
    };
  }

  eolFor(chemistry: string | null | undefined) {
    return this.options?.eol_criteria.find((c) => c.chemistry.toUpperCase() === (chemistry ?? '').trim().toUpperCase()) ?? null;
  }

  get editProblem(): string | null {
    const v = this.edit?.values;
    if (!v) {
      return null;
    }
    if (!(v.chemistry ?? '').trim()) {
      return 'Chemistry is required';
    }
    for (const f of NUM_FIELDS) {
      const x = v[f.key] as unknown;
      if (x === null || x === undefined || x === '') {
        continue;
      }
      const n = Number(x);
      if (!Number.isFinite(n)) {
        return `${f.label} must be a number`;
      }
      if (f.positive && n <= 0) {
        return `${f.label} must be above 0`;
      }
      if ((f.min !== undefined && n < f.min) || (f.max !== undefined && n > f.max)) {
        return `${f.label} must be between ${f.min} and ${f.max}`;
      }
    }
    const cap = Number(v.bol_capacity_kwh);
    const name = Number(v.nameplate_kwh);
    if (cap > 0 && name > 0 && (cap > name * 1.3 || cap < name * 0.7)) {
      return 'BOL capacity should be within ±30 % of the nameplate';
    }
    return null;
  }

  save(): void {
    const e = this.edit;
    if (!e || this.editProblem) {
      return;
    }
    const v = e.values;
    const t = (x: string | null) => (x ?? '').trim() || null;
    const n = (x: unknown) => (x === null || x === undefined || x === '' ? null : Number(x));
    const body: BatteryProvenanceValues = {
      manufacturer: t(v.manufacturer),
      cell_model: t(v.cell_model),
      chemistry: v.chemistry.trim().toUpperCase(),
      batch_lot: t(v.batch_lot),
      cell_format: t(v.cell_format),
      build_date: t(v.build_date),
      nameplate_kwh: n(v.nameplate_kwh),
      bol_capacity_kwh: n(v.bol_capacity_kwh),
      bol_resistance_mohm: n(v.bol_resistance_mohm),
      usage_cycles_per_day: n(v.usage_cycles_per_day),
      climate_avg_temp_c: n(v.climate_avg_temp_c)
    };
    this.saving = true;
    this.editError = null;
    this.service.update(e.row.system_id, body).subscribe({
      next: () => {
        this.saving = false;
        this.edit = null;
        this.fetchRows();
        this.loadOptions();
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
    this.toDelete = this.rows.find((x) => x.system_id === (row as unknown as BatteryProvenance).system_id) ?? null;
  }

  deleteConfirmed(): void {
    const t = this.toDelete;
    if (!t) {
      return;
    }
    this.deleting = true;
    this.service.delete(t.system_id).subscribe({
      next: () => {
        this.deleting = false;
        this.toDelete = null;
        this.fetchRows();
        this.loadOptions();
      },
      error: (err) => {
        this.deleting = false;
        this.deleteError = err?.error?.detail || 'Deleting failed.';
      }
    });
  }
}
