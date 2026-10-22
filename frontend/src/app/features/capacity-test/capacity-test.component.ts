import { CommonModule } from '@angular/common';
import { Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { CapacityTest, CapacityTestPage, CapacityTestSystem, CapacityTestValues } from '../../core/models/capacity-test.model';
import { CapacityTestService } from '../../core/services/capacity-test.service';
import { ColumnPickerComponent } from '../telemetry/table/column-picker.component';
import { TableColumn, TableRow } from '../telemetry/table/table-column';
import { TelemetryTableComponent } from '../telemetry/table/telemetry-table.component';

const PAGE_SIZE_OPTIONS = [50, 100, 250];

const TEST_COLUMNS: TableColumn[] = [
  { key: 'system_code', label: 'System', kind: 'text', group: 'Test', locked: true },
  { key: 'test_date', label: 'Test Date', kind: 'text', group: 'Test', locked: true },
  { key: 'method', label: 'Method', kind: 'text', group: 'Test' },
  { key: 'test_temp_c', label: 'Test Temp (°C)', kind: 'number', group: 'Test' },
  { key: 'age_days', label: 'Age (days)', kind: 'number', group: 'Age' },
  { key: 'equiv_full_cycles', label: 'Equiv. Full Cycles', kind: 'number', group: 'Age' },
  { key: 'measured_capacity_kwh', label: 'Measured Capacity (kWh)', kind: 'number', group: 'Result' },
  { key: 'soh_pct', label: 'SOH (%)', kind: 'number', group: 'Result' },
  { key: 'internal_resistance_mohm', label: 'Int. Resistance (mΩ)', kind: 'number', group: 'Result' },
  { key: 'test_id', label: 'Test ID', kind: 'number', group: 'Record' }
];
const DEFAULT_KEYS = TEST_COLUMNS.filter((c) => c.key !== 'test_id').map((c) => c.key);

const SORTS: { key: string; label: string }[] = [
  { key: 'test_date', label: 'Test date' },
  { key: 'system_id', label: 'System' },
  { key: 'age_days', label: 'Age' },
  { key: 'equiv_full_cycles', label: 'Equivalent full cycles' },
  { key: 'measured_capacity_kwh', label: 'Measured capacity' },
  { key: 'soh_pct', label: 'SOH' },
  { key: 'internal_resistance_mohm', label: 'Internal resistance' }
];

interface NumField {
  key: keyof CapacityTestValues;
  label: string;
  step: number;
  integer?: boolean;
  min?: number;
  max?: number;
}

const NUM_FIELDS: NumField[] = [
  { key: 'age_days', label: 'Age (days)', step: 1, integer: true, min: 0 },
  { key: 'equiv_full_cycles', label: 'Equivalent full cycles', step: 0.1, min: 0 },
  { key: 'measured_capacity_kwh', label: 'Measured capacity (kWh)', step: 0.1, min: 0 },
  { key: 'soh_pct', label: 'SOH (%)', step: 0.01, min: 0, max: 110 },
  { key: 'internal_resistance_mohm', label: 'Internal resistance (mΩ)', step: 0.001, min: 0 },
  { key: 'test_temp_c', label: 'Test temperature (°C)', step: 0.1, min: -40, max: 100 }
];

interface EditState {
  row: CapacityTest;
  values: CapacityTestValues;
}

/** Core -> Reference -> Capacity Tests: periodic RPT capacity / resistance checkpoints of the RUL fleet systems
 *  (battery_master.capacity_test, the SOH ground truth); view, filter, edit and delete. */
@Component({
  selector: 'app-capacity-test',
  standalone: true,
  imports: [CommonModule, FormsModule, ColumnPickerComponent, TelemetryTableComponent],
  templateUrl: './capacity-test.component.html',
  styleUrls: ['../calendar/calendar.component.scss', '../aging-snapshot/aging-snapshot.component.scss']
})
export class CapacityTestComponent implements OnInit {
  readonly allColumns = TEST_COLUMNS;
  readonly defaultColumnKeys = DEFAULT_KEYS;
  readonly sorts = SORTS;
  readonly numFields = NUM_FIELDS;
  visibleColumns: TableColumn[] = TEST_COLUMNS.filter((c) => DEFAULT_KEYS.includes(c.key));

  systems: CapacityTestSystem[] = [];
  methods: string[] = [];
  page: CapacityTestPage | null = null;
  tableRows: TableRow[] = [];
  loading = true;
  error: string | null = null;

  filterSystem: number | null = null;
  filterStart = '';
  filterEnd = '';
  filterMethod = '';
  sort = 'test_date';
  order: 'asc' | 'desc' = 'asc';
  pageSizeOptions = PAGE_SIZE_OPTIONS;
  pageSize = PAGE_SIZE_OPTIONS[0];
  currentPage = 1;

  edit: EditState | null = null;
  saving = false;
  editError: string | null = null;
  toDelete: CapacityTest | null = null;
  deleting = false;
  deleteError: string | null = null;

  constructor(private service: CapacityTestService) {}

  ngOnInit(): void {
    this.loadSystems();
    this.fetchRows();
  }

  // ---------------------------------------------------------------- summary

  loadSystems(): void {
    this.service.systems().subscribe({ next: (s) => (this.systems = s), error: () => (this.systems = []) });
    this.service.methods().subscribe({ next: (m) => (this.methods = m), error: () => (this.methods = []) });
  }

  get fleet() {
    const s = this.systems.filter((x) => x.tests > 0);
    const dates = s.flatMap((x) => [x.first_date, x.last_date]).filter((d): d is string => !!d).sort();
    const fades = s.map((x) => this.fade(x)).filter((v): v is number => v !== null);
    return {
      systems: s.length,
      tests: s.reduce((a, x) => a + x.tests, 0),
      first: dates[0] ?? null,
      last: dates[dates.length - 1] ?? null,
      maxFade: fades.length ? Math.max(...fades) : null
    };
  }

  /** Capacity lost between a system's first and latest test (%). */
  fade(s: CapacityTestSystem): number | null {
    return s.first_capacity_kwh && s.latest_capacity_kwh !== null ? 100 * (1 - s.latest_capacity_kwh / s.first_capacity_kwh) : null;
  }

  selectSystem(id: number): void {
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
        method: this.filterMethod || undefined,
        sort: this.sort,
        order: this.order,
        page: this.currentPage,
        pageSize: this.pageSize
      })
      .subscribe({
        next: (page) => {
          this.page = page;
          this.tableRows = page.items.map((r) => ({ ...r, method: r.method ?? '—' }) as unknown as TableRow);
          this.loading = false;
        },
        error: () => {
          this.error = 'Could not load the capacity tests. Is the backend running?';
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
    this.filterMethod = '';
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
    const r = row as unknown as CapacityTest;
    const values = { test_date: r.test_date, method: r.method === '—' ? '' : r.method } as CapacityTestValues;
    for (const f of NUM_FIELDS) {
      (values as any)[f.key] = r[f.key];
    }
    this.editError = null;
    this.edit = { row: r, values };
  }

  get editProblem(): string | null {
    const e = this.edit;
    if (!e) {
      return null;
    }
    if (!/^\d{4}-\d{2}-\d{2}$/.test(e.values.test_date ?? '')) {
      return 'Enter the test date';
    }
    for (const f of NUM_FIELDS) {
      const v = e.values[f.key] as unknown;
      if (v === null || v === undefined || v === '') {
        continue;
      }
      const n = Number(v);
      if (!Number.isFinite(n)) {
        return `${f.label} must be a number`;
      }
      if (f.integer && !Number.isInteger(n)) {
        return `${f.label} must be a whole number`;
      }
      if ((f.min !== undefined && n < f.min) || (f.max !== undefined && n > f.max)) {
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
    const body = { ...e.values, method: (e.values.method ?? '').trim() || null };
    for (const f of NUM_FIELDS) {
      const v = body[f.key] as unknown;
      (body as any)[f.key] = v === null || v === undefined || v === '' ? null : Number(v);
    }
    this.saving = true;
    this.editError = null;
    this.service.update(e.row.test_id, body).subscribe({
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
    this.toDelete = row as unknown as CapacityTest;
  }

  deleteConfirmed(): void {
    const t = this.toDelete;
    if (!t) {
      return;
    }
    this.deleting = true;
    this.service.delete(t.test_id).subscribe({
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
