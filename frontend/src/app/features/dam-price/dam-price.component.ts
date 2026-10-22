import { CommonModule } from '@angular/common';
import { Component, ElementRef, OnInit, ViewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { BulkDamPriceResult, DamPrice, DamPricePage, PriceNode } from '../../core/models/dam-price.model';
import { DamPriceService } from '../../core/services/dam-price.service';
import { ColumnPickerComponent } from '../telemetry/table/column-picker.component';
import { TableColumn, TableRow } from '../telemetry/table/table-column';
import { TelemetryTableComponent } from '../telemetry/table/telemetry-table.component';

const PAGE_SIZE_OPTIONS = [24, 48, 96, 168];
const BLOCK_OPTIONS = [5, 15, 30, 60];

const DAM_COLUMNS: TableColumn[] = [
  { key: 'start_label', label: 'Delivery Start', kind: 'text', group: 'Block', locked: true },
  { key: 'end_label', label: 'Delivery End', kind: 'text', group: 'Block' },
  { key: 'node_code', label: 'Node', kind: 'text', group: 'Block' },
  { key: 'block_minutes', label: 'Block (min)', kind: 'number', group: 'Block' },
  { key: 'price_mwh', label: 'Price (USD/MWh)', kind: 'number', group: 'Market' },
  { key: 'cleared_mw', label: 'Cleared (MW)', kind: 'number', group: 'Market' },
  { key: 'cleared_mwh', label: 'Cleared Energy (MWh)', kind: 'number', group: 'Market' },
  { key: 'band', label: 'Price Band', kind: 'text', group: 'Market' }
];
const DEFAULT_KEYS = ['start_label', 'end_label', 'node_code', 'block_minutes', 'price_mwh', 'cleared_mw'];

interface EditState {
  mode: 'add' | 'edit';
  node_id: number | null;
  /** datetime-local value, plant time: 2026-08-01T05:00 */
  start_local: string;
  /** original ISO key (edit only) */
  key: string;
  block_minutes: number;
  price_mwh: number | null;
  cleared_mw: number | null;
}

/** "2026-08-01T05:00:00+05:30" -> "2026-08-01 05:00" in plant time, read straight from the string (no browser tz). */
function plantLabel(iso: string): string {
  return iso.slice(0, 10) + ' ' + iso.slice(11, 16);
}

/** Wall-clock arithmetic on the plant-time part of an ISO string. */
function addMinutes(iso: string, minutes: number): string {
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number);
  const [hh, mm] = iso.slice(11, 16).split(':').map(Number);
  const t = new Date(Date.UTC(y, m - 1, d, hh, mm + minutes));
  return t.toISOString().slice(0, 10) + ' ' + t.toISOString().slice(11, 16);
}

/** Core -> Market Data -> DAM Price: day-ahead cleared prices per settlement node and delivery block;
 *  upload dam_price.csv, add / edit / delete blocks, tabular view with price statistics. */
@Component({
  selector: 'app-dam-price',
  standalone: true,
  imports: [CommonModule, FormsModule, ColumnPickerComponent, TelemetryTableComponent],
  templateUrl: './dam-price.component.html',
  styleUrl: './dam-price.component.scss'
})
export class DamPriceComponent implements OnInit {
  @ViewChild('fileInput') fileInput?: ElementRef<HTMLInputElement>;

  nodes: PriceNode[] = [];

  // upload
  showUpload = false;
  selectedFile: File | null = null;
  uploadNodeId: number | null = null;
  uploading = false;
  uploadResult: BulkDamPriceResult | null = null;
  uploadError: string | null = null;
  showAllUploadErrors = false;

  // table
  readonly allColumns = DAM_COLUMNS;
  readonly defaultColumnKeys = DEFAULT_KEYS;
  visibleColumns: TableColumn[] = DAM_COLUMNS.filter((c) => DEFAULT_KEYS.includes(c.key));
  page: DamPricePage | null = null;
  tableRows: TableRow[] = [];
  loading = true;
  error: string | null = null;
  filterNode: number | null = null;
  filterStart = '';
  filterEnd = '';
  filterMin: number | null = null;
  filterMax: number | null = null;
  order: 'asc' | 'desc' = 'asc';
  pageSizeOptions = PAGE_SIZE_OPTIONS;
  pageSize = 48;
  currentPage = 1;

  // add / edit / delete
  readonly blockOptions = BLOCK_OPTIONS;
  edit: EditState | null = null;
  saving = false;
  editError: string | null = null;
  toDelete: DamPrice | null = null;
  deleting = false;
  deleteError: string | null = null;

  constructor(private service: DamPriceService) {}

  ngOnInit(): void {
    this.loadNodes();
    this.fetchRows();
  }

  loadNodes(): void {
    this.service.nodes().subscribe({
      next: (nodes) => (this.nodes = nodes),
      error: () => (this.nodes = [])
    });
  }

  get currency(): string {
    return this.nodes[0]?.currency ?? 'USD';
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

  label(iso: string | null | undefined): string {
    return iso ? plantLabel(iso) : '—';
  }

  fetchRows(): void {
    this.loading = true;
    this.error = null;
    this.service
      .list({
        nodeId: this.filterNode,
        start: this.filterStart || undefined,
        end: this.filterEnd || undefined,
        minPrice: this.filterMin,
        maxPrice: this.filterMax,
        order: this.order,
        page: this.currentPage,
        pageSize: this.pageSize
      })
      .subscribe({
        next: (page) => {
          this.page = page;
          const s = page.stats;
          // thirds of the filtered price range: a quick cheap / mid / peak read for arbitrage
          const lo = s.min_price ?? 0;
          const span = (s.max_price ?? 0) - lo;
          this.tableRows = page.items.map(
            (p) =>
              ({
                ...p,
                start_label: plantLabel(p.delivery_start),
                end_label: addMinutes(p.delivery_start, p.block_minutes),
                cleared_mwh: p.cleared_mw == null ? null : +((p.cleared_mw * p.block_minutes) / 60).toFixed(3),
                band: span <= 0 ? '—' : p.price_mwh < lo + span / 3 ? 'Low' : p.price_mwh < lo + (2 * span) / 3 ? 'Mid' : 'Peak'
              }) as unknown as TableRow
          );
          this.loading = false;
        },
        error: () => {
          this.error = 'Could not load DAM prices. Is the backend running?';
          this.loading = false;
        }
      });
  }

  applyFilters(): void {
    this.currentPage = 1;
    this.fetchRows();
  }

  clearFilters(): void {
    this.filterNode = null;
    this.filterStart = '';
    this.filterEnd = '';
    this.filterMin = null;
    this.filterMax = null;
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
    this.service.bulkUpload(this.selectedFile, this.uploadNodeId).subscribe({
      next: (result) => {
        this.uploadResult = result;
        this.uploading = false;
        this.selectedFile = null;
        if (this.fileInput) {
          this.fileInput.nativeElement.value = '';
        }
        this.currentPage = 1;
        this.loadNodes();
        this.fetchRows();
      },
      error: (err) => {
        this.uploadError = err?.error?.detail || 'Upload failed. Is the backend running?';
        this.uploading = false;
      }
    });
  }

  // ---------------------------------------------------------------- add / edit / delete

  openAdd(): void {
    // next block after the latest one loaded, else today 00:00
    const last = this.page?.stats.last_start;
    const next = last ? addMinutes(last, 60).replace(' ', 'T') : new Date().toISOString().slice(0, 10) + 'T00:00';
    this.editError = null;
    this.edit = {
      mode: 'add',
      node_id: this.filterNode ?? this.nodes[0]?.node_id ?? null,
      start_local: next,
      key: '',
      block_minutes: 60,
      price_mwh: null,
      cleared_mw: null
    };
  }

  openEdit(row: TableRow): void {
    const r = row as unknown as DamPrice;
    this.editError = null;
    this.edit = {
      mode: 'edit',
      node_id: r.node_id,
      start_local: r.delivery_start.slice(0, 16),
      key: r.delivery_start,
      block_minutes: r.block_minutes,
      price_mwh: r.price_mwh,
      cleared_mw: r.cleared_mw
    };
  }

  nodeCode(id: number | null): string {
    return this.nodes.find((n) => n.node_id === id)?.node_code ?? '—';
  }

  get editProblem(): string | null {
    const e = this.edit;
    if (!e) {
      return null;
    }
    if (e.node_id == null) {
      return 'Choose a price node';
    }
    if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(e.start_local)) {
      return 'Enter the delivery start';
    }
    const minutes = Number(e.start_local.slice(11, 13)) * 60 + Number(e.start_local.slice(14, 16));
    if (minutes % e.block_minutes !== 0) {
      return `Delivery start must be on a ${e.block_minutes}-minute boundary`;
    }
    if (e.price_mwh == null || isNaN(e.price_mwh)) {
      return 'Enter the price';
    }
    if (e.price_mwh < -1000 || e.price_mwh > 20000) {
      return 'Price must be between -1000 and 20000';
    }
    if (e.cleared_mw != null && e.cleared_mw < 0) {
      return 'Cleared volume cannot be negative';
    }
    return null;
  }

  save(): void {
    const e = this.edit;
    if (!e || this.editProblem || e.node_id == null || e.price_mwh == null) {
      return;
    }
    const body = { block_minutes: e.block_minutes, price_mwh: e.price_mwh, cleared_mw: e.cleared_mw ?? null };
    this.saving = true;
    this.editError = null;
    const req$ =
      e.mode === 'add'
        ? this.service.add({ ...body, node_id: e.node_id, delivery_start: e.start_local.slice(0, 16) + ':00' })
        : this.service.update(e.node_id, e.key, body);
    req$.subscribe({
      next: () => {
        this.saving = false;
        this.edit = null;
        this.loadNodes();
        this.fetchRows();
      },
      error: (err) => {
        this.saving = false;
        const d = err?.error?.detail;
        this.editError = Array.isArray(d)
          ? d.map((x: { loc?: string[]; msg: string }) => `${x.loc?.slice(-1)[0] ?? ''}: ${x.msg.replace(/^Value error, /, '')}`).join('; ')
          : d || 'Saving failed.';
      }
    });
  }

  confirmDelete(row: TableRow): void {
    this.deleteError = null;
    this.toDelete = row as unknown as DamPrice;
  }

  deleteConfirmed(): void {
    const t = this.toDelete;
    if (!t) {
      return;
    }
    this.deleting = true;
    this.service.delete(t.node_id, t.delivery_start).subscribe({
      next: () => {
        this.deleting = false;
        this.toDelete = null;
        this.loadNodes();
        this.fetchRows();
      },
      error: (err) => {
        this.deleting = false;
        this.deleteError = err?.error?.detail || 'Deleting failed.';
      }
    });
  }
}
