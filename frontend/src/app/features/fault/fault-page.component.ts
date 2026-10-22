import { CommonModule } from '@angular/common';
import { Component, ElementRef, OnInit, ViewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute } from '@angular/router';

import { FaultBulkResult, FaultEnumSource, FaultLookupSource, FaultLookups, FaultPage, FaultRow } from '../../core/models/fault.model';
import { FaultService } from '../../core/services/fault.service';
import { ColumnPickerComponent } from '../telemetry/table/column-picker.component';
import { TableColumn, TableRow } from '../telemetry/table/table-column';
import { TelemetryTableComponent } from '../telemetry/table/telemetry-table.component';
import { FAULT_PAGES, FaultFieldDef, FaultFilterDef, FaultPageConfig } from './fault-page.config';

interface Choice {
  value: string | number | boolean;
  label: string;
}

interface EditState {
  mode: 'add' | 'edit';
  values: Record<string, unknown>;
  key: (string | number)[];
  title: string;
}

/** "2026-08-01T05:00:00+05:30" -> "2026-08-01 05:00" in plant time, read straight from the string (no browser tz). */
function plantLabel(iso: unknown): string {
  return typeof iso === 'string' && iso.length >= 16 ? iso.slice(0, 10) + ' ' + iso.slice(11, 16) : '—';
}

function blank(v: unknown): boolean {
  return v === null || v === undefined || v === '' || (typeof v === 'number' && isNaN(v));
}

const BOOL_CHOICES: Choice[] = [
  { value: true, label: 'Yes' },
  { value: false, label: 'No' }
];

/** Core -> Fault: one page per fault-diagnosis table (catalog, signature, episode, alarm link, maintenance action,
 *  prediction), described by FAULT_PAGES[route data `page`]. Upload a CSV / XLSX, filter, search, page through,
 *  add / edit / delete rows; the summary bar comes from the API. Same screen as the BMS / Dispatch pages. */
@Component({
  selector: 'app-fault-page',
  standalone: true,
  imports: [CommonModule, FormsModule, ColumnPickerComponent, TelemetryTableComponent],
  templateUrl: './fault-page.component.html',
  styleUrl: './fault-page.component.scss'
})
export class FaultPageComponent implements OnInit {
  @ViewChild('fileInput') fileInput?: ElementRef<HTMLInputElement>;

  cfg!: FaultPageConfig;
  lookups: FaultLookups | null = null;

  showUpload = false;
  selectedFile: File | null = null;
  uploading = false;
  uploadResult: FaultBulkResult | null = null;
  uploadError: string | null = null;
  showAllUploadErrors = false;

  visibleColumns: TableColumn[] = [];
  page: FaultPage | null = null;
  tableRows: TableRow[] = [];
  loading = true;
  error: string | null = null;
  filters: Record<string, unknown> = {};
  search = '';
  filterStart = '';
  filterEnd = '';
  order: 'asc' | 'desc' = 'asc';
  pageSize = 50;
  currentPage = 1;

  edit: EditState | null = null;
  saving = false;
  editError: string | null = null;
  toDelete: FaultRow | null = null;
  deleting = false;
  deleteError: string | null = null;

  readonly label = plantLabel;

  constructor(
    private route: ActivatedRoute,
    private service: FaultService
  ) {}

  ngOnInit(): void {
    // the same component serves every fault table: re-initialize when the route's page changes
    this.route.data.subscribe((d) => {
      this.cfg = FAULT_PAGES[d['page'] as string];
      this.visibleColumns = this.cfg.columns.filter((c) => this.cfg.defaultColumns.includes(c.key));
      this.filters = this.emptyFilters();
      this.search = '';
      this.filterStart = '';
      this.filterEnd = '';
      this.order = this.cfg.defaultOrder;
      this.pageSize = this.cfg.pageSizes[1] ?? this.cfg.pageSizes[0];
      this.currentPage = 1;
      this.uploadResult = null;
      this.uploadError = null;
      this.selectedFile = null;
      this.loadLookups();
      this.fetchRows();
    });
  }

  get storageKey(): string {
    return `bess.fault.${this.cfg.endpoint}.columns`;
  }

  loadLookups(): void {
    this.service.lookups().subscribe({
      next: (l) => (this.lookups = l),
      error: () => (this.lookups = null)
    });
  }

  choices(def: { from?: FaultLookupSource; options?: FaultEnumSource; kind?: string }): Choice[] {
    if (def.kind === 'bool') {
      return BOOL_CHOICES;
    }
    const l = this.lookups;
    if (!l) {
      return [];
    }
    switch (def.from) {
      case 'systems':
        return l.systems.map((o) => ({ value: o.id, label: o.code }));
      case 'faults':
        return l.faults.map((o) => ({ value: o.code, label: o.label }));
      case 'episodes':
        return l.episodes.map((o) => ({ value: o.code, label: o.label }));
      case 'model_versions':
        return l.model_versions.map((v) => ({ value: v, label: v }));
      case 'categories':
        return l.categories.map((v) => ({ value: v, label: v }));
    }
    if (def.options) {
      return (l[def.options] as (string | number | boolean)[]).map((v) => ({ value: v, label: String(v) }));
    }
    return [];
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
    const query: Record<string, string | number | boolean | null | undefined> = {
      start: this.cfg.dateLabel ? this.filterStart || null : null,
      end: this.cfg.dateLabel ? this.filterEnd || null : null,
      q: this.search.trim() || null,
      order: this.order,
      page: this.currentPage,
      page_size: this.pageSize
    };
    for (const f of this.cfg.filters) {
      const v = this.filters[f.param];
      query[f.param] = blank(v) ? null : (v as string | number | boolean);
    }
    const endpoint = this.cfg.endpoint;
    this.service.list(endpoint, query).subscribe({
      next: (page) => {
        if (endpoint !== this.cfg.endpoint) {
          return; // a stale answer for the previous page
        }
        this.page = page;
        this.tableRows = page.items.map((r) => {
          const row: FaultRow = { ...r };
          for (const f of this.cfg.tsFields) {
            row[`${f}_label`] = plantLabel(r[f]);
          }
          for (const f of this.cfg.boolFields) {
            row[`${f}_label`] = r[f] === true ? 'Yes' : r[f] === false ? 'No' : '—';
          }
          return row as TableRow;
        });
        this.loading = false;
      },
      error: () => {
        this.error = `Could not load ${this.cfg.title.toLowerCase()} rows. Is the backend running?`;
        this.loading = false;
      }
    });
  }

  applyFilters(): void {
    this.currentPage = 1;
    this.fetchRows();
  }

  private emptyFilters(): Record<string, unknown> {
    return Object.fromEntries(this.cfg.filters.map((f) => [f.param, null]));
  }

  clearFilters(): void {
    this.filters = this.emptyFilters();
    this.search = '';
    this.filterStart = '';
    this.filterEnd = '';
    this.currentPage = 1;
    this.fetchRows();
  }

  toggleOrder(): void {
    this.order = this.order === 'asc' ? 'desc' : 'asc';
    this.currentPage = 1;
    this.fetchRows();
  }

  setPageSize(size: number): void {
    this.pageSize = size;
    this.currentPage = 1;
    this.fetchRows();
  }

  goToPage(page: number): void {
    if (page >= 1 && page <= this.totalPages) {
      this.currentPage = page;
      this.fetchRows();
    }
  }

  trackFilter(_: number, f: FaultFilterDef): string {
    return f.param;
  }

  // ---------------------------------------------------------------- upload

  get visibleUploadErrors() {
    if (!this.uploadResult) {
      return [];
    }
    return this.showAllUploadErrors ? this.uploadResult.errors : this.uploadResult.errors.slice(0, 10);
  }

  onFileSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    this.selectedFile = input.files && input.files.length > 0 ? input.files[0] : null;
    this.uploadResult = null;
    this.uploadError = null;
    this.showAllUploadErrors = false;
  }

  upload(): void {
    if (!this.selectedFile) {
      return;
    }
    this.uploading = true;
    this.uploadError = null;
    this.uploadResult = null;
    this.service.bulkUpload(this.cfg.endpoint, this.selectedFile).subscribe({
      next: (result) => {
        this.uploadResult = result;
        this.uploading = false;
        this.selectedFile = null;
        if (this.fileInput) {
          this.fileInput.nativeElement.value = '';
        }
        this.currentPage = 1;
        this.loadLookups();
        this.fetchRows();
      },
      error: (err) => {
        this.uploadError = err?.error?.detail || 'Upload failed. Is the backend running?';
        this.uploading = false;
      }
    });
  }

  // ---------------------------------------------------------------- add / edit / delete

  get editFields(): FaultFieldDef[] {
    return this.cfg.fields;
  }

  fieldLocked(f: FaultFieldDef): boolean {
    return this.edit?.mode === 'edit' && !!f.isKey;
  }

  openAdd(): void {
    const values: Record<string, unknown> = { ...(this.cfg.defaults ?? {}) };
    for (const f of this.cfg.fields) {
      if (!blank(this.filters[f.key]) && f.kind === 'select') {
        values[f.key] = this.filters[f.key];
      }
    }
    this.editError = null;
    this.edit = { mode: 'add', values, key: [], title: `Add ${this.cfg.noun}` };
  }

  openEdit(row: TableRow): void {
    const r = row as FaultRow;
    const values: Record<string, unknown> = {};
    for (const f of this.cfg.fields) {
      const v = r[f.key];
      values[f.key] = f.kind === 'datetime' && typeof v === 'string' ? v.slice(0, 16) : v;
    }
    this.editError = null;
    this.edit = {
      mode: 'edit',
      values,
      key: this.cfg.keyFields.map((k) => r[k] as string | number),
      title: `Edit ${this.cfg.describe(r, plantLabel)}`
    };
  }

  get editProblem(): string | null {
    const e = this.edit;
    if (!e) {
      return null;
    }
    const missing = this.editFields.filter((f) => f.required && blank(e.values[f.key]));
    return missing.length ? `Fill in ${missing.map((f) => f.label.replace(/ \(.*\)$/, '')).join(', ')}` : null;
  }

  private payload(): FaultRow {
    const e = this.edit!;
    const body: FaultRow = {};
    for (const f of this.editFields) {
      if (e.mode === 'edit' && f.isKey) {
        continue;
      }
      const v = e.values[f.key];
      let out: unknown;
      if (blank(v)) {
        out = null;
      } else if (f.kind === 'number' || f.kind === 'int') {
        out = Number(v);
      } else if (f.kind === 'datetime') {
        out = String(v).slice(0, 16) + ':00';
      } else if (f.kind === 'select' || f.kind === 'bool') {
        out = v;
      } else {
        out = String(v).trim() || null;
      }
      body[f.key] = out;
    }
    return body;
  }

  save(): void {
    const e = this.edit;
    if (!e || this.editProblem) {
      return;
    }
    this.saving = true;
    this.editError = null;
    const body = this.payload();
    const req$ = e.mode === 'add' ? this.service.add(this.cfg.endpoint, body) : this.service.update(this.cfg.endpoint, e.key, body);
    req$.subscribe({
      next: () => {
        this.saving = false;
        this.edit = null;
        this.loadLookups();
        this.fetchRows();
      },
      error: (err) => {
        this.saving = false;
        const d = err?.error?.detail;
        this.editError = Array.isArray(d)
          ? d.map((x: { loc?: (string | number)[]; msg: string }) => {
              const field = x.loc && x.loc.length > 1 ? `${x.loc[x.loc.length - 1]}: ` : '';
              return field + x.msg.replace(/^Value error, /, '');
            }).join('; ')
          : d || 'Saving failed.';
      }
    });
  }

  confirmDelete(row: TableRow): void {
    this.deleteError = null;
    this.toDelete = row as FaultRow;
  }

  deleteConfirmed(): void {
    const t = this.toDelete;
    if (!t) {
      return;
    }
    this.deleting = true;
    this.service.delete(this.cfg.endpoint, this.cfg.keyFields.map((k) => t[k] as string | number)).subscribe({
      next: () => {
        this.deleting = false;
        this.toDelete = null;
        this.loadLookups();
        this.fetchRows();
      },
      error: (err) => {
        this.deleting = false;
        this.deleteError = err?.error?.detail || 'Deleting failed.';
      }
    });
  }
}
