import { CommonModule } from '@angular/common';
import { Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { LifecycleEvent, LifecycleEventPage, LifecycleEventValues, LifecycleSystem } from '../../core/models/lifecycle-event.model';
import { LifecycleEventService } from '../../core/services/lifecycle-event.service';
import { ColumnPickerComponent } from '../telemetry/table/column-picker.component';
import { TableColumn, TableRow } from '../telemetry/table/table-column';
import { TelemetryTableComponent } from '../telemetry/table/telemetry-table.component';

const PAGE_SIZE_OPTIONS = [50, 100, 250];

const EVENT_COLUMNS: TableColumn[] = [
  { key: 'system_code', label: 'System', kind: 'text', group: 'Event', locked: true },
  { key: 'event_date', label: 'Event Date', kind: 'text', group: 'Event', locked: true },
  { key: 'type_label', label: 'Event Type', kind: 'text', group: 'Event', locked: true },
  { key: 'age_days', label: 'Age (days)', kind: 'number', group: 'State' },
  { key: 'soh_at_event', label: 'SOH at Event (%)', kind: 'number', group: 'State' },
  { key: 'failure_mode', label: 'Failure Mode', kind: 'text', group: 'Detail' },
  { key: 'note', label: 'Note', kind: 'text', group: 'Detail' },
  { key: 'event_id', label: 'Event ID', kind: 'number', group: 'Record' }
];
const DEFAULT_KEYS = EVENT_COLUMNS.filter((c) => c.key !== 'event_id').map((c) => c.key);

/** Readable names of the event types (chk_evt). */
export const EVENT_LABELS: Record<string, string> = {
  COMMISSION: 'Commissioned',
  AUGMENTATION: 'Augmentation',
  MODULE_REPLACE: 'Module replaced',
  EOL_REACHED: 'End of life reached',
  FAILURE: 'Failure',
  DECOMMISSION: 'Decommissioned'
};

const SORTS: { key: string; label: string }[] = [
  { key: 'event_date', label: 'Event date' },
  { key: 'system_id', label: 'System' },
  { key: 'event_type', label: 'Event type' },
  { key: 'age_days', label: 'Age' },
  { key: 'soh_at_event', label: 'SOH at event' }
];

interface EditState {
  row: LifecycleEvent;
  values: LifecycleEventValues;
}

/** Core -> Reference -> Lifecycle Events: commissioning, augmentation, module replacement, end of life, failure and
 *  decommissioning events of the RUL fleet systems (battery_master.lifecycle_event); view, filter, edit and delete. */
@Component({
  selector: 'app-lifecycle-event',
  standalone: true,
  imports: [CommonModule, FormsModule, ColumnPickerComponent, TelemetryTableComponent],
  templateUrl: './lifecycle-event.component.html',
  styleUrls: ['../calendar/calendar.component.scss', '../aging-snapshot/aging-snapshot.component.scss', './lifecycle-event.component.scss']
})
export class LifecycleEventComponent implements OnInit {
  readonly allColumns = EVENT_COLUMNS;
  readonly defaultColumnKeys = DEFAULT_KEYS;
  readonly sorts = SORTS;
  readonly labels = EVENT_LABELS;
  visibleColumns: TableColumn[] = EVENT_COLUMNS.filter((c) => DEFAULT_KEYS.includes(c.key));

  types: string[] = Object.keys(EVENT_LABELS);
  systems: LifecycleSystem[] = [];
  page: LifecycleEventPage | null = null;
  tableRows: TableRow[] = [];
  loading = true;
  error: string | null = null;

  filterSystem: number | null = null;
  filterType = '';
  filterStart = '';
  filterEnd = '';
  sort = 'event_date';
  order: 'asc' | 'desc' = 'asc';
  pageSizeOptions = PAGE_SIZE_OPTIONS;
  pageSize = PAGE_SIZE_OPTIONS[0];
  currentPage = 1;

  edit: EditState | null = null;
  saving = false;
  editError: string | null = null;
  toDelete: LifecycleEvent | null = null;
  deleting = false;
  deleteError: string | null = null;

  constructor(private service: LifecycleEventService) {}

  ngOnInit(): void {
    this.service.types().subscribe({ next: (t) => (this.types = t), error: () => undefined });
    this.loadSystems();
    this.fetchRows();
  }

  // ---------------------------------------------------------------- summary

  loadSystems(): void {
    this.service.systems().subscribe({ next: (s) => (this.systems = s), error: () => (this.systems = []) });
  }

  label(t: string | null | undefined): string {
    return t ? EVENT_LABELS[t] ?? t : '—';
  }

  count(t: string): number {
    return this.page?.counts[t] ?? 0;
  }

  get countedTypes(): string[] {
    return this.types.filter((t) => this.count(t) > 0);
  }

  selectSystem(id: number): void {
    this.filterSystem = this.filterSystem === id ? null : id;
    this.applyFilters();
  }

  selectType(t: string): void {
    this.filterType = this.filterType === t ? '' : t;
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
        eventType: this.filterType || undefined,
        start: this.filterStart || undefined,
        end: this.filterEnd || undefined,
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
                type_label: this.label(r.event_type),
                failure_mode: r.failure_mode ?? '—',
                note: r.note ?? '—'
              }) as unknown as TableRow
          );
          this.loading = false;
        },
        error: () => {
          this.error = 'Could not load the lifecycle events. Is the backend running?';
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
    this.filterType = '';
    this.filterStart = '';
    this.filterEnd = '';
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
    const r = row as unknown as LifecycleEvent;
    this.editError = null;
    this.edit = {
      row: r,
      values: {
        event_type: r.event_type,
        event_date: r.event_date,
        age_days: r.age_days,
        soh_at_event: r.soh_at_event,
        failure_mode: r.failure_mode === '—' ? '' : r.failure_mode,
        note: r.note === '—' ? '' : r.note
      }
    };
  }

  get editProblem(): string | null {
    const v = this.edit?.values;
    if (!v) {
      return null;
    }
    if (!/^\d{4}-\d{2}-\d{2}$/.test(v.event_date ?? '')) {
      return 'Enter the event date';
    }
    const age = v.age_days as unknown;
    if (age !== null && age !== '' && (!Number.isInteger(Number(age)) || Number(age) < 0)) {
      return 'Age must be a whole number of days, 0 or more';
    }
    const soh = v.soh_at_event as unknown;
    if (soh !== null && soh !== '' && !(Number(soh) >= 0 && Number(soh) <= 110)) {
      return 'SOH at event must be between 0 and 110 %';
    }
    return null;
  }

  save(): void {
    const e = this.edit;
    if (!e || this.editProblem) {
      return;
    }
    const v = e.values;
    const n = (x: unknown) => (x === null || x === undefined || x === '' ? null : Number(x));
    const body: LifecycleEventValues = {
      event_type: v.event_type,
      event_date: v.event_date,
      age_days: n(v.age_days),
      soh_at_event: n(v.soh_at_event),
      failure_mode: (v.failure_mode ?? '').trim() || null,
      note: (v.note ?? '').trim() || null
    };
    this.saving = true;
    this.editError = null;
    this.service.update(e.row.event_id, body).subscribe({
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
    this.toDelete = row as unknown as LifecycleEvent;
  }

  deleteConfirmed(): void {
    const t = this.toDelete;
    if (!t) {
      return;
    }
    this.deleting = true;
    this.service.delete(t.event_id).subscribe({
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
