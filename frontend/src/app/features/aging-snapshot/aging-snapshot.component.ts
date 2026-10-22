import { CommonModule } from '@angular/common';
import { Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { AgingSnapshot, AgingSnapshotPage, AgingSnapshotValues, AgingSystemSummary } from '../../core/models/aging-snapshot.model';
import { AgingSnapshotService } from '../../core/services/aging-snapshot.service';
import { ColumnPickerComponent } from '../telemetry/table/column-picker.component';
import { TableColumn, TableRow } from '../telemetry/table/table-column';
import { TelemetryTableComponent } from '../telemetry/table/telemetry-table.component';

const PAGE_SIZE_OPTIONS = [50, 100, 250];

const AGING_COLUMNS: TableColumn[] = [
  { key: 'system_code', label: 'System', kind: 'text', group: 'Key', locked: true },
  { key: 'snapshot_date', label: 'Snapshot Date', kind: 'text', group: 'Key', locked: true },
  { key: 'age_days', label: 'Age (days)', kind: 'number', group: 'Age' },
  { key: 'calendar_age_years', label: 'Calendar Age (y)', kind: 'number', group: 'Age' },
  { key: 'cum_throughput_mwh', label: 'Throughput (MWh)', kind: 'number', group: 'Usage' },
  { key: 'equiv_full_cycles', label: 'Equiv. Full Cycles', kind: 'number', group: 'Usage' },
  { key: 'avg_dod_pct', label: 'Avg DoD (%)', kind: 'number', group: 'Usage' },
  { key: 'avg_cell_temp_c', label: 'Avg Cell Temp (°C)', kind: 'number', group: 'Stress' },
  { key: 'days_at_high_soc', label: 'Days at High SOC', kind: 'number', group: 'Stress' },
  { key: 'soh_pct', label: 'SOH (%)', kind: 'number', group: 'Health' },
  { key: 'internal_resistance_mohm', label: 'Int. Resistance (mΩ)', kind: 'number', group: 'Health' },
  { key: 'rul_cycles', label: 'RUL (cycles)', kind: 'number', group: 'RUL label' },
  { key: 'rul_days', label: 'RUL (days)', kind: 'number', group: 'RUL label' },
  { key: 'censored_label', label: 'Censored', kind: 'text', group: 'RUL label' },
  { key: 'eol_label', label: 'EOL Reached', kind: 'text', group: 'RUL label' }
];

const SORTS: { key: string; label: string }[] = [
  { key: 'snapshot_date', label: 'Snapshot date' },
  { key: 'system_id', label: 'System' },
  { key: 'age_days', label: 'Age' },
  { key: 'soh_pct', label: 'SOH' },
  { key: 'rul_days', label: 'RUL (days)' },
  { key: 'equiv_full_cycles', label: 'Equivalent full cycles' },
  { key: 'internal_resistance_mohm', label: 'Internal resistance' }
];

interface NumField {
  key: keyof AgingSnapshotValues;
  label: string;
  step: number;
  integer?: boolean;
  min?: number;
  max?: number;
}

const NUM_FIELDS: NumField[] = [
  { key: 'age_days', label: 'Age (days)', step: 1, integer: true, min: 0 },
  { key: 'calendar_age_years', label: 'Calendar age (years)', step: 0.01, min: 0 },
  { key: 'cum_throughput_mwh', label: 'Cumulative throughput (MWh)', step: 0.1, min: 0 },
  { key: 'equiv_full_cycles', label: 'Equivalent full cycles', step: 0.1, min: 0 },
  { key: 'avg_dod_pct', label: 'Average DoD (%)', step: 0.1, min: 0, max: 100 },
  { key: 'avg_cell_temp_c', label: 'Average cell temp (°C)', step: 0.1, min: -40, max: 100 },
  { key: 'days_at_high_soc', label: 'Days at high SOC', step: 0.1, min: 0 },
  { key: 'soh_pct', label: 'SOH (%)', step: 0.01, min: 0, max: 120 },
  { key: 'internal_resistance_mohm', label: 'Internal resistance (mΩ)', step: 0.001, min: 0 },
  { key: 'rul_cycles', label: 'RUL (cycles)', step: 0.1, min: 0 },
  { key: 'rul_days', label: 'RUL (days)', step: 1, integer: true, min: 0 }
];

interface EditState {
  row: AgingSnapshot;
  values: AgingSnapshotValues;
}

/** Core -> Reference -> Aging Snapshots: monthly aging features and RUL labels of the RUL fleet systems
 *  (battery_master.aging_snapshot); view, filter, edit and delete. */
@Component({
  selector: 'app-aging-snapshot',
  standalone: true,
  imports: [CommonModule, FormsModule, ColumnPickerComponent, TelemetryTableComponent],
  templateUrl: './aging-snapshot.component.html',
  styleUrls: ['../calendar/calendar.component.scss', './aging-snapshot.component.scss']
})
export class AgingSnapshotComponent implements OnInit {
  readonly allColumns = AGING_COLUMNS;
  readonly defaultColumnKeys = AGING_COLUMNS.map((c) => c.key);
  readonly sorts = SORTS;
  readonly numFields = NUM_FIELDS;
  visibleColumns: TableColumn[] = AGING_COLUMNS;

  systems: AgingSystemSummary[] = [];
  page: AgingSnapshotPage | null = null;
  tableRows: TableRow[] = [];
  loading = true;
  error: string | null = null;

  filterSystem: number | null = null;
  filterStart = '';
  filterEnd = '';
  filterEol: '' | 'true' | 'false' = '';
  filterCensored: '' | 'true' | 'false' = '';
  sort = 'snapshot_date';
  order: 'asc' | 'desc' = 'asc';
  pageSizeOptions = PAGE_SIZE_OPTIONS;
  pageSize = PAGE_SIZE_OPTIONS[0];
  currentPage = 1;

  edit: EditState | null = null;
  saving = false;
  editError: string | null = null;
  toDelete: AgingSnapshot | null = null;
  deleting = false;
  deleteError: string | null = null;

  constructor(private service: AgingSnapshotService) {}

  ngOnInit(): void {
    this.loadSystems();
    this.fetchRows();
  }

  // ---------------------------------------------------------------- summary

  loadSystems(): void {
    this.service.systems().subscribe({ next: (s) => (this.systems = s), error: () => (this.systems = []) });
  }

  get fleet() {
    const s = this.systems.filter((x) => x.snapshots > 0);
    const dates = s.flatMap((x) => [x.first_date, x.last_date]).filter((d): d is string => !!d).sort();
    return {
      systems: s.length,
      snapshots: s.reduce((a, x) => a + x.snapshots, 0),
      eol: s.filter((x) => x.eol_reached).length,
      first: dates[0] ?? null,
      last: dates[dates.length - 1] ?? null
    };
  }

  selectSystem(id: number | null): void {
    this.filterSystem = this.filterSystem === id ? null : id;
    this.applyFilters();
  }

  // ---------------------------------------------------------------- table

  get total(): number {
    return this.page?.total ?? 0;
  }

  get totalPages(): number {
    return Math.max(1, Math.ceil(this.total / this.pageSize));
  }

  get rangeStart(): number {
    return this.total === 0 ? 0 : (this.currentPage - 1) * this.pageSize + 1;
  }

  get rangeEnd(): number {
    return Math.min(this.currentPage * this.pageSize, this.total);
  }

  fetchRows(): void {
    this.loading = true;
    this.error = null;
    this.service
      .list({
        systemId: this.filterSystem,
        start: this.filterStart || undefined,
        end: this.filterEnd || undefined,
        eol: this.filterEol === '' ? null : this.filterEol === 'true',
        censored: this.filterCensored === '' ? null : this.filterCensored === 'true',
        sort: this.sort,
        order: this.order,
        page: this.currentPage,
        pageSize: this.pageSize
      })
      .subscribe({
        next: (page) => {
          this.page = page;
          this.tableRows = page.items.map(
            (r) =>
              ({
                ...r,
                censored_label: r.is_censored === null ? '—' : r.is_censored ? 'Yes' : 'No',
                eol_label: r.eol_reached === null ? '—' : r.eol_reached ? 'Yes' : 'No'
              }) as unknown as TableRow
          );
          this.loading = false;
        },
        error: () => {
          this.error = 'Could not load the aging snapshots. Is the backend running?';
          this.loading = false;
        }
      });
  }

  applyFilters(): void {
    this.currentPage = 1;
    this.fetchRows();
  }

  clearFilters(): void {
    this.filterSystem = null;
    this.filterStart = '';
    this.filterEnd = '';
    this.filterEol = '';
    this.filterCensored = '';
    this.applyFilters();
  }

  toggleOrder(): void {
    this.order = this.order === 'asc' ? 'desc' : 'asc';
    this.applyFilters();
  }

  setPageSize(size: number): void {
    this.pageSize = size;
    this.applyFilters();
  }

  goToPage(page: number): void {
    if (page >= 1 && page <= this.totalPages) {
      this.currentPage = page;
      this.fetchRows();
    }
  }

  num(v: number | null | undefined, d = 1): string {
    return typeof v === 'number' && Number.isFinite(v) ? v.toFixed(d) : '—';
  }

  // ---------------------------------------------------------------- edit / delete

  openEdit(row: TableRow): void {
    const r = row as unknown as AgingSnapshot;
    const values = {} as AgingSnapshotValues;
    for (const f of NUM_FIELDS) {
      (values as any)[f.key] = r[f.key];
    }
    values.is_censored = r.is_censored;
    values.eol_reached = r.eol_reached;
    this.editError = null;
    this.edit = { row: r, values };
  }

  get editProblem(): string | null {
    const e = this.edit;
    if (!e) {
      return null;
    }
    for (const f of NUM_FIELDS) {
      const v = e.values[f.key] as number | null;
      if (v === null || v === undefined || (v as unknown) === '') {
        continue;
      }
      if (!Number.isFinite(Number(v))) {
        return `${f.label} must be a number`;
      }
      if (f.integer && !Number.isInteger(Number(v))) {
        return `${f.label} must be a whole number`;
      }
      if ((f.min !== undefined && Number(v) < f.min) || (f.max !== undefined && Number(v) > f.max)) {
        return `${f.label} must be between ${f.min ?? '−∞'} and ${f.max ?? '∞'}`;
      }
    }
    return null;
  }

  save(): void {
    const e = this.edit;
    if (!e || this.editProblem) {
      return;
    }
    const body = { ...e.values };
    for (const f of NUM_FIELDS) {
      const v = body[f.key] as unknown;
      (body as any)[f.key] = v === null || v === undefined || v === '' ? null : Number(v);
    }
    this.saving = true;
    this.editError = null;
    this.service.update(e.row.system_id, e.row.snapshot_date, body).subscribe({
      next: () => {
        this.saving = false;
        this.edit = null;
        this.fetchRows();
        this.loadSystems();
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
    this.toDelete = row as unknown as AgingSnapshot;
  }

  deleteConfirmed(): void {
    const t = this.toDelete;
    if (!t) {
      return;
    }
    this.deleting = true;
    this.service.delete(t.system_id, t.snapshot_date).subscribe({
      next: () => {
        this.deleting = false;
        this.toDelete = null;
        this.fetchRows();
        this.loadSystems();
      },
      error: (err) => {
        this.deleting = false;
        this.deleteError = err?.error?.detail || 'Deleting failed.';
      }
    });
  }
}
