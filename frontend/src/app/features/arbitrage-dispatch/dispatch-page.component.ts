import { CommonModule } from '@angular/common';
import { Component, ElementRef, OnInit, ViewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute } from '@angular/router';

import { ArbBulkResult, ArbLookups, ArbPage, ArbRow, EnumSource, LookupSource } from '../../core/models/arbitrage.model';
import { ArbitrageService } from '../../core/services/arbitrage.service';
import { ColumnPickerComponent } from '../telemetry/table/column-picker.component';
import { TableColumn, TableRow } from '../telemetry/table/table-column';
import { TelemetryTableComponent } from '../telemetry/table/telemetry-table.component';
import { DISPATCH_PAGES, DispatchPageConfig, FieldDef, FilterDef } from './dispatch-page.config';

interface Choice {
  value: string | number;
  label: string;
}

interface EditState {
  mode: 'add' | 'edit';
  values: Record<string, unknown>;
  /** key of the row being edited, in cfg.keyFields order */
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

/** Core -> Dispatch: one page per arbitrage decision table (optimization run, decision state, dispatch schedule /
 *  outcome, AS award, price scenario), described by DISPATCH_PAGES[route data `page`]. Upload a pack CSV / XLSX,
 *  filter, page through, add / edit / delete rows; the summary bar comes from the API. */
@Component({
  selector: 'app-dispatch-page',
  standalone: true,
  imports: [CommonModule, FormsModule, ColumnPickerComponent, TelemetryTableComponent],
  templateUrl: './dispatch-page.component.html',
  styleUrl: './dispatch-page.component.scss'
})
export class DispatchPageComponent implements OnInit {
  @ViewChild('fileInput') fileInput?: ElementRef<HTMLInputElement>;

  cfg!: DispatchPageConfig;
  lookups: ArbLookups | null = null;

  // upload
  showUpload = false;
  selectedFile: File | null = null;
  uploading = false;
  uploadResult: ArbBulkResult | null = null;
  uploadError: string | null = null;
  showAllUploadErrors = false;

  // table
  visibleColumns: TableColumn[] = [];
  page: ArbPage | null = null;
  tableRows: TableRow[] = [];
  loading = true;
  error: string | null = null;
  filters: Record<string, unknown> = {};
  filterStart = '';
  filterEnd = '';
  order: 'asc' | 'desc' = 'asc';
  pageSize = 50;
  currentPage = 1;

  // add / edit / delete
  edit: EditState | null = null;
  saving = false;
  editError: string | null = null;
  toDelete: ArbRow | null = null;
  deleting = false;
  deleteError: string | null = null;

  readonly label = plantLabel;

  constructor(
    private route: ActivatedRoute,
    private service: ArbitrageService
  ) {}

  ngOnInit(): void {
    this.cfg = DISPATCH_PAGES[this.route.snapshot.data['page'] as string];
    this.visibleColumns = this.cfg.columns.filter((c) => this.cfg.defaultColumns.includes(c.key));
    this.filters = this.emptyFilters();
    this.order = this.cfg.defaultOrder;
    this.pageSize = this.cfg.pageSizes[1] ?? this.cfg.pageSizes[0];
    this.loadLookups();
    this.fetchRows();
  }

  get storageKey(): string {
    return `bess.dispatch.${this.cfg.endpoint}.columns`;
  }

  loadLookups(): void {
    this.service.lookups().subscribe({
      next: (l) => (this.lookups = l),
      error: () => (this.lookups = null)
    });
  }

  /** Choices of a lookup- or enum-backed picker. */
  choices(def: { from?: LookupSource; options?: EnumSource }): Choice[] {
    const l = this.lookups;
    if (!l) {
      return [];
    }
    switch (def.from) {
      case 'systems':
        return l.systems.map((o) => ({ value: o.id, label: o.code }));
      case 'nodes':
        return l.nodes.map((o) => ({ value: o.id, label: o.code }));
      case 'products':
        return l.products.map((o) => ({ value: o.id, label: o.label ? `${o.code} · ${o.label}` : o.code }));
      case 'runs':
        return l.runs.map((r) => ({
          value: r.run_id,
          label: `#${r.run_id} · ${r.system_code} · ${plantLabel(r.horizon_start)} → ${plantLabel(r.horizon_end).slice(11)}`
        }));
      case 'scenario_vintages':
        return l.scenario_vintages.map((v) => ({ value: v, label: plantLabel(v) }));
    }
    if (def.options) {
      return (l[def.options] as (string | number)[]).map((v) => ({ value: v, label: String(v) }));
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
    const query: Record<string, string | number | null | undefined> = {
      start: this.filterStart || null,
      end: this.filterEnd || null,
      order: this.order,
      page: this.currentPage,
      page_size: this.pageSize
    };
    for (const f of this.cfg.filters) {
      const v = this.filters[f.param];
      query[f.param] = blank(v) ? null : (v as string | number);
    }
    this.service.list(this.cfg.endpoint, query).subscribe({
      next: (page) => {
        this.page = page;
        this.tableRows = page.items.map((r) => {
          const row: ArbRow = { ...r };
          for (const f of this.cfg.tsFields) {
            row[`${f}_label`] = plantLabel(r[f]);
          }
          return { ...row, ...(this.cfg.derive ? this.cfg.derive(r) : {}) } as TableRow;
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

  /** Every filter starts at null so its select shows the "All" option. */
  private emptyFilters(): Record<string, unknown> {
    return Object.fromEntries(this.cfg.filters.map((f) => [f.param, null]));
  }

  clearFilters(): void {
    this.filters = this.emptyFilters();
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

  trackFilter(_: number, f: FilterDef): string {
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

  get editFields(): FieldDef[] {
    return this.edit?.mode === 'edit' ? this.cfg.fields.filter((f) => !f.createOnly) : this.cfg.fields;
  }

  fieldLocked(f: FieldDef): boolean {
    return this.edit?.mode === 'edit' && !!f.isKey;
  }

  openAdd(): void {
    const values: Record<string, unknown> = { ...(this.cfg.defaults ?? {}) };
    // start from the current filter's system / run / node / product when it matches a field
    for (const f of this.cfg.fields) {
      if (!blank(this.filters[f.key]) && f.kind === 'select' && f.from && f.from !== 'scenario_vintages') {
        values[f.key] = this.filters[f.key];
      }
    }
    this.editError = null;
    this.edit = { mode: 'add', values, key: [], title: `Add ${this.cfg.noun}` };
  }

  openEdit(row: TableRow): void {
    const r = row as ArbRow;
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

  private payload(): ArbRow {
    const e = this.edit!;
    const body: ArbRow = {};
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
      } else if (f.kind === 'select') {
        out = f.from === 'scenario_vintages' || (f.options && f.options !== 'resolutions') ? v : Number(v);
      } else {
        out = String(v).trim() || null;
      }
      if (out === null && f.createOnly) {
        continue;
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
    const req$ =
      e.mode === 'add'
        ? this.service.add(this.cfg.endpoint, body)
        : this.service.update(this.cfg.endpoint, e.key, body);
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
          ? d
              .map((x: { loc?: (string | number)[]; msg: string }) => {
                const field = x.loc && x.loc.length > 1 ? `${x.loc[x.loc.length - 1]}: ` : '';
                return field + x.msg.replace(/^Value error, /, '');
              })
              .join('; ')
          : d || 'Saving failed.';
      }
    });
  }

  confirmDelete(row: TableRow): void {
    this.deleteError = null;
    this.toDelete = row as ArbRow;
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
