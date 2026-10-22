import { CommonModule } from '@angular/common';
import { Component, ElementRef, OnInit, ViewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { AsPrice, AsPricePage, AsProduct, BulkAsPriceResult } from '../../core/models/as-price.model';
import { AsPriceService } from '../../core/services/as-price.service';
import { ColumnPickerComponent } from '../telemetry/table/column-picker.component';
import { TableColumn, TableRow } from '../telemetry/table/table-column';
import { TelemetryTableComponent } from '../telemetry/table/telemetry-table.component';

const PAGE_SIZE_OPTIONS = [24, 48, 96, 168];
const BLOCK_OPTIONS = [5, 15, 30, 60];

const AS_COLUMNS: TableColumn[] = [
  { key: 'start_label', label: 'Delivery Start', kind: 'text', group: 'Block', locked: true },
  { key: 'end_label', label: 'Delivery End', kind: 'text', group: 'Block' },
  { key: 'product_code', label: 'Product', kind: 'text', group: 'Block' },
  { key: 'product_name', label: 'Product Name', kind: 'text', group: 'Block' },
  { key: 'block_minutes', label: 'Block (min)', kind: 'number', group: 'Block' },
  { key: 'capacity_price_mw', label: 'Capacity Price (USD/MW)', kind: 'number', group: 'Prices' },
  { key: 'performance_price', label: 'Performance Price (USD/MW)', kind: 'number', group: 'Prices' },
  { key: 'total_price', label: 'Capacity + Performance', kind: 'number', group: 'Prices' }
];
const DEFAULT_KEYS = ['start_label', 'end_label', 'product_code', 'block_minutes', 'capacity_price_mw', 'performance_price'];

interface EditState {
  mode: 'add' | 'edit';
  product_id: number | null;
  /** datetime-local value, plant time: 2026-08-01T05:00 */
  start_local: string;
  /** original ISO key (edit only) */
  key: string;
  block_minutes: number;
  capacity_price_mw: number | null;
  performance_price: number | null;
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

function emptyNum(v: number | null | undefined): boolean {
  return v == null || (typeof v === 'number' && isNaN(v)) || (v as unknown) === '';
}

/** Core -> Market Data -> AS Price: ancillary-service capacity / performance clearing prices per product and
 *  delivery block; upload as_price.csv, add / edit / delete blocks, tabular view with price statistics. */
@Component({
  selector: 'app-as-price',
  standalone: true,
  imports: [CommonModule, FormsModule, ColumnPickerComponent, TelemetryTableComponent],
  templateUrl: './as-price.component.html',
  styleUrl: './as-price.component.scss'
})
export class AsPriceComponent implements OnInit {
  @ViewChild('fileInput') fileInput?: ElementRef<HTMLInputElement>;

  products: AsProduct[] = [];

  // upload
  showUpload = false;
  selectedFile: File | null = null;
  uploadProductId: number | null = null;
  uploading = false;
  uploadResult: BulkAsPriceResult | null = null;
  uploadError: string | null = null;
  showAllUploadErrors = false;

  // table
  readonly allColumns = AS_COLUMNS;
  readonly defaultColumnKeys = DEFAULT_KEYS;
  visibleColumns: TableColumn[] = AS_COLUMNS.filter((c) => DEFAULT_KEYS.includes(c.key));
  page: AsPricePage | null = null;
  tableRows: TableRow[] = [];
  loading = true;
  error: string | null = null;
  filterProduct: number | null = null;
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
  toDelete: AsPrice | null = null;
  deleting = false;
  deleteError: string | null = null;

  constructor(private service: AsPriceService) {}

  ngOnInit(): void {
    this.loadProducts();
    this.fetchRows();
  }

  loadProducts(): void {
    this.service.products().subscribe({
      next: (products) => (this.products = products),
      error: () => (this.products = [])
    });
  }

  get currency(): string {
    return this.products[0]?.currency ?? 'USD';
  }

  product(id: number | null): AsProduct | undefined {
    return this.products.find((p) => p.product_id === id);
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
        productId: this.filterProduct,
        start: this.filterStart || undefined,
        end: this.filterEnd || undefined,
        minCapacity: this.filterMin,
        maxCapacity: this.filterMax,
        order: this.order,
        page: this.currentPage,
        pageSize: this.pageSize
      })
      .subscribe({
        next: (page) => {
          this.page = page;
          this.tableRows = page.items.map(
            (p) =>
              ({
                ...p,
                start_label: plantLabel(p.delivery_start),
                end_label: addMinutes(p.delivery_start, p.block_minutes),
                product_name: this.product(p.product_id)?.name ?? '',
                total_price:
                  p.capacity_price_mw == null && p.performance_price == null
                    ? null
                    : +((p.capacity_price_mw ?? 0) + (p.performance_price ?? 0)).toFixed(2)
              }) as unknown as TableRow
          );
          this.loading = false;
        },
        error: () => {
          this.error = 'Could not load AS prices. Is the backend running?';
          this.loading = false;
        }
      });
  }

  applyFilters(): void {
    this.currentPage = 1;
    this.fetchRows();
  }

  clearFilters(): void {
    this.filterProduct = null;
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
    this.service.bulkUpload(this.selectedFile, this.uploadProductId).subscribe({
      next: (result) => {
        this.uploadResult = result;
        this.uploading = false;
        this.selectedFile = null;
        if (this.fileInput) {
          this.fileInput.nativeElement.value = '';
        }
        this.currentPage = 1;
        this.loadProducts();
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
      product_id: this.filterProduct ?? this.products[0]?.product_id ?? null,
      start_local: next,
      key: '',
      block_minutes: 60,
      capacity_price_mw: null,
      performance_price: null
    };
  }

  openEdit(row: TableRow): void {
    const r = row as unknown as AsPrice;
    this.editError = null;
    this.edit = {
      mode: 'edit',
      product_id: r.product_id,
      start_local: r.delivery_start.slice(0, 16),
      key: r.delivery_start,
      block_minutes: r.block_minutes,
      capacity_price_mw: r.capacity_price_mw,
      performance_price: r.performance_price
    };
  }

  get editProblem(): string | null {
    const e = this.edit;
    if (!e) {
      return null;
    }
    if (e.product_id == null) {
      return 'Choose an AS product';
    }
    if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(e.start_local)) {
      return 'Enter the delivery start';
    }
    const minutes = Number(e.start_local.slice(11, 13)) * 60 + Number(e.start_local.slice(14, 16));
    if (minutes % e.block_minutes !== 0) {
      return `Delivery start must be on a ${e.block_minutes}-minute boundary`;
    }
    const cap = emptyNum(e.capacity_price_mw) ? null : e.capacity_price_mw;
    const perf = emptyNum(e.performance_price) ? null : e.performance_price;
    if (cap == null && perf == null) {
      return 'Enter a capacity price, a performance price or both';
    }
    if ((cap != null && (cap < 0 || cap > 100000)) || (perf != null && (perf < 0 || perf > 100000))) {
      return 'Prices must be between 0 and 100000';
    }
    return null;
  }

  save(): void {
    const e = this.edit;
    if (!e || this.editProblem || e.product_id == null) {
      return;
    }
    const body = {
      block_minutes: e.block_minutes,
      capacity_price_mw: emptyNum(e.capacity_price_mw) ? null : e.capacity_price_mw,
      performance_price: emptyNum(e.performance_price) ? null : e.performance_price
    };
    this.saving = true;
    this.editError = null;
    const req$ =
      e.mode === 'add'
        ? this.service.add({ ...body, product_id: e.product_id, delivery_start: e.start_local.slice(0, 16) + ':00' })
        : this.service.update(e.product_id, e.key, body);
    req$.subscribe({
      next: () => {
        this.saving = false;
        this.edit = null;
        this.loadProducts();
        this.fetchRows();
      },
      error: (err) => {
        this.saving = false;
        const d = err?.error?.detail;
        this.editError = Array.isArray(d)
          ? d.map((x: { msg: string }) => x.msg.replace(/^Value error, /, '')).join('; ')
          : d || 'Saving failed.';
      }
    });
  }

  confirmDelete(row: TableRow): void {
    this.deleteError = null;
    this.toDelete = row as unknown as AsPrice;
  }

  deleteConfirmed(): void {
    const t = this.toDelete;
    if (!t) {
      return;
    }
    this.deleting = true;
    this.service.delete(t.product_id, t.delivery_start).subscribe({
      next: () => {
        this.deleting = false;
        this.toDelete = null;
        this.loadProducts();
        this.fetchRows();
      },
      error: (err) => {
        this.deleting = false;
        this.deleteError = err?.error?.detail || 'Deleting failed.';
      }
    });
  }
}
