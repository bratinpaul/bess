import { CommonModule } from '@angular/common';
import { Component, ElementRef, OnInit, ViewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { PriceNode } from '../../core/models/dam-price.model';
import {
  BulkPriceForecastResult,
  ForecastVintage,
  PriceForecast,
  PriceForecastPage
} from '../../core/models/market-price-forecast.model';
import { DamPriceService } from '../../core/services/dam-price.service';
import { MarketPriceForecastService } from '../../core/services/market-price-forecast.service';
import { ColumnPickerComponent } from '../telemetry/table/column-picker.component';
import { TableColumn, TableRow } from '../telemetry/table/table-column';
import { TelemetryTableComponent } from '../telemetry/table/telemetry-table.component';

const PAGE_SIZE_OPTIONS = [24, 48, 96, 168];

const PF_COLUMNS: TableColumn[] = [
  { key: 'target_label', label: 'Target Hour', kind: 'text', group: 'Forecast', locked: true },
  { key: 'issued_label', label: 'Issued At', kind: 'text', group: 'Forecast' },
  { key: 'horizon_h', label: 'Horizon (h)', kind: 'number', group: 'Forecast' },
  { key: 'node_code', label: 'Node', kind: 'text', group: 'Forecast' },
  { key: 'model', label: 'Model', kind: 'text', group: 'Forecast' },
  { key: 'p10_mwh', label: 'P10 (USD/MWh)', kind: 'number', group: 'Quantiles' },
  { key: 'p50_mwh', label: 'P50 (USD/MWh)', kind: 'number', group: 'Quantiles' },
  { key: 'p90_mwh', label: 'P90 (USD/MWh)', kind: 'number', group: 'Quantiles' },
  { key: 'band_width', label: 'P90 − P10', kind: 'number', group: 'Quantiles' },
  { key: 'actual_mwh', label: 'Actual DAM', kind: 'number', group: 'Accuracy' },
  { key: 'error_mwh', label: 'P50 − Actual', kind: 'number', group: 'Accuracy' },
  { key: 'in_band_label', label: 'Actual in P10–P90', kind: 'text', group: 'Accuracy' }
];
const DEFAULT_KEYS = ['target_label', 'issued_label', 'horizon_h', 'p10_mwh', 'p50_mwh', 'p90_mwh', 'actual_mwh', 'error_mwh', 'in_band_label'];

interface EditState {
  mode: 'add' | 'edit';
  node_id: number | null;
  /** datetime-local values, plant time: 2026-08-01T10:00 */
  issued_local: string;
  target_local: string;
  /** original ISO keys (edit only) */
  issued_key: string;
  target_key: string;
  p10_mwh: number | null;
  p50_mwh: number | null;
  p90_mwh: number | null;
  model: string;
  actual_mwh: number | null;
}

/** "2026-08-01T05:00:00+05:30" -> "2026-08-01 05:00" in plant time, read straight from the string (no browser tz). */
function plantLabel(iso: string): string {
  return iso.slice(0, 10) + ' ' + iso.slice(11, 16);
}

/** Wall-clock arithmetic on a plant-time "YYYY-MM-DDTHH:MM" value. */
function addHours(local: string, hours: number): string {
  const [y, m, d] = local.slice(0, 10).split('-').map(Number);
  const [hh, mm] = local.slice(11, 16).split(':').map(Number);
  return new Date(Date.UTC(y, m - 1, d, hh + hours, mm)).toISOString().slice(0, 16);
}

function hoursBetween(fromLocal: string, toLocal: string): number | null {
  const ok = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/;
  if (!ok.test(fromLocal) || !ok.test(toLocal)) {
    return null;
  }
  const t = (s: string) => Date.UTC(+s.slice(0, 4), +s.slice(5, 7) - 1, +s.slice(8, 10), +s.slice(11, 13), +s.slice(14, 16));
  return Math.round(((t(toLocal) - t(fromLocal)) / 3_600_000) * 100) / 100;
}

function emptyNum(v: number | null | undefined): boolean {
  return v == null || (typeof v === 'number' && isNaN(v)) || (v as unknown) === '';
}

/** Core -> Market Data -> Price Forecast: probabilistic (P10 / P50 / P90) price forecasts per node, issue vintage and
 *  target hour, scored against the realized DAM price; upload price_forecast.csv, add / edit / delete rows. */
@Component({
  selector: 'app-market-price-forecast',
  standalone: true,
  imports: [CommonModule, FormsModule, ColumnPickerComponent, TelemetryTableComponent],
  templateUrl: './market-price-forecast.component.html',
  styleUrl: './market-price-forecast.component.scss'
})
export class MarketPriceForecastComponent implements OnInit {
  @ViewChild('fileInput') fileInput?: ElementRef<HTMLInputElement>;

  nodes: PriceNode[] = [];
  vintages: ForecastVintage[] = [];
  models: string[] = [];

  // upload
  showUpload = false;
  selectedFile: File | null = null;
  uploadNodeId: number | null = null;
  uploading = false;
  uploadResult: BulkPriceForecastResult | null = null;
  uploadError: string | null = null;
  showAllUploadErrors = false;

  // table
  readonly allColumns = PF_COLUMNS;
  readonly defaultColumnKeys = DEFAULT_KEYS;
  visibleColumns: TableColumn[] = PF_COLUMNS.filter((c) => DEFAULT_KEYS.includes(c.key));
  page: PriceForecastPage | null = null;
  tableRows: TableRow[] = [];
  loading = true;
  error: string | null = null;
  filterNode: number | null = null;
  filterVintage: string | null = null;
  filterStart = '';
  filterEnd = '';
  filterModel: string | null = null;
  order: 'asc' | 'desc' = 'asc';
  pageSizeOptions = PAGE_SIZE_OPTIONS;
  pageSize = 48;
  currentPage = 1;

  // add / edit / delete
  edit: EditState | null = null;
  saving = false;
  editError: string | null = null;
  toDelete: PriceForecast | null = null;
  deleting = false;
  deleteError: string | null = null;

  constructor(
    private service: MarketPriceForecastService,
    private nodeService: DamPriceService
  ) {}

  ngOnInit(): void {
    this.nodeService.nodes().subscribe({
      next: (nodes) => (this.nodes = nodes),
      error: () => (this.nodes = [])
    });
    this.loadLookups();
    this.fetchRows();
  }

  loadLookups(): void {
    this.service.vintages().subscribe({
      next: (v) => (this.vintages = v),
      error: () => (this.vintages = [])
    });
    this.service.models().subscribe({
      next: (m) => (this.models = m),
      error: () => (this.models = [])
    });
  }

  get currency(): string {
    return this.nodes[0]?.currency ?? 'USD';
  }

  nodeCode(id: number | null): string {
    return this.nodes.find((n) => n.node_id === id)?.node_code ?? '—';
  }

  /** Vintages of the chosen node (all when no node is chosen). */
  get vintageOptions(): ForecastVintage[] {
    return this.filterNode == null ? this.vintages : this.vintages.filter((v) => v.node_id === this.filterNode);
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
        issuedAt: this.filterVintage,
        start: this.filterStart || undefined,
        end: this.filterEnd || undefined,
        model: this.filterModel,
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
                target_label: plantLabel(p.target_ts),
                issued_label: plantLabel(p.issued_at),
                band_width: p.p10_mwh == null || p.p90_mwh == null ? null : +(p.p90_mwh - p.p10_mwh).toFixed(2),
                in_band_label: p.in_band == null ? '—' : p.in_band ? 'Yes' : 'No'
              }) as unknown as TableRow
          );
          this.loading = false;
        },
        error: () => {
          this.error = 'Could not load price forecasts. Is the backend running?';
          this.loading = false;
        }
      });
  }

  onNodeChange(): void {
    // a vintage of another node would return nothing
    if (this.filterVintage && !this.vintageOptions.some((v) => v.issued_at === this.filterVintage)) {
      this.filterVintage = null;
    }
  }

  applyFilters(): void {
    this.currentPage = 1;
    this.fetchRows();
  }

  clearFilters(): void {
    this.filterNode = null;
    this.filterVintage = null;
    this.filterStart = '';
    this.filterEnd = '';
    this.filterModel = null;
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

  openAdd(): void {
    // a new day-ahead vintage: the day after the latest one, issued 10:00, first target the next midnight
    const latest = this.vintages[0]?.issued_at;
    const issued = latest
      ? addHours(latest.slice(0, 16), 24)
      : new Date().toISOString().slice(0, 10) + 'T10:00';
    this.editError = null;
    this.edit = {
      mode: 'add',
      node_id: this.filterNode ?? this.nodes[0]?.node_id ?? null,
      issued_local: issued,
      target_local: addHours(issued.slice(0, 10) + 'T00:00', 24),
      issued_key: '',
      target_key: '',
      p10_mwh: null,
      p50_mwh: null,
      p90_mwh: null,
      model: this.models[0] ?? '',
      actual_mwh: null
    };
  }

  openEdit(row: TableRow): void {
    const r = row as unknown as PriceForecast;
    this.editError = null;
    this.edit = {
      mode: 'edit',
      node_id: r.node_id,
      issued_local: r.issued_at.slice(0, 16),
      target_local: r.target_ts.slice(0, 16),
      issued_key: r.issued_at,
      target_key: r.target_ts,
      p10_mwh: r.p10_mwh,
      p50_mwh: r.p50_mwh,
      p90_mwh: r.p90_mwh,
      model: r.model ?? '',
      actual_mwh: r.actual_mwh
    };
  }

  get editHorizon(): number | null {
    return this.edit ? hoursBetween(this.edit.issued_local, this.edit.target_local) : null;
  }

  get editProblem(): string | null {
    const e = this.edit;
    if (!e) {
      return null;
    }
    if (e.node_id == null) {
      return 'Choose a price node';
    }
    const h = this.editHorizon;
    if (h == null) {
      return 'Enter the issue and target times';
    }
    if (h <= 0) {
      return 'Target must be after the issue time';
    }
    if (h > 336) {
      return 'Horizon is beyond two weeks';
    }
    if (emptyNum(e.p50_mwh)) {
      return 'Enter the P50';
    }
    const p50 = e.p50_mwh as number;
    const p10 = emptyNum(e.p10_mwh) ? null : e.p10_mwh;
    const p90 = emptyNum(e.p90_mwh) ? null : e.p90_mwh;
    if ([p10, p50, p90].some((v) => v != null && (v < -1000 || v > 20000))) {
      return 'Prices must be between -1000 and 20000';
    }
    if (p10 != null && p10 > p50) {
      return 'P10 must not be above P50';
    }
    if (p90 != null && p90 < p50) {
      return 'P90 must not be below P50';
    }
    return null;
  }

  save(): void {
    const e = this.edit;
    if (!e || this.editProblem || e.node_id == null || e.p50_mwh == null) {
      return;
    }
    const body = {
      p10_mwh: emptyNum(e.p10_mwh) ? null : e.p10_mwh,
      p50_mwh: e.p50_mwh,
      p90_mwh: emptyNum(e.p90_mwh) ? null : e.p90_mwh,
      model: e.model.trim() || null
    };
    this.saving = true;
    this.editError = null;
    const req$ =
      e.mode === 'add'
        ? this.service.add({
            ...body,
            node_id: e.node_id,
            issued_at: e.issued_local.slice(0, 16) + ':00',
            target_ts: e.target_local.slice(0, 16) + ':00'
          })
        : this.service.update(e.node_id, e.issued_key, e.target_key, body);
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
          ? d.map((x: { msg: string }) => x.msg.replace(/^Value error, /, '')).join('; ')
          : d || 'Saving failed.';
      }
    });
  }

  confirmDelete(row: TableRow): void {
    this.deleteError = null;
    this.toDelete = row as unknown as PriceForecast;
  }

  deleteConfirmed(): void {
    const t = this.toDelete;
    if (!t) {
      return;
    }
    this.deleting = true;
    this.service.delete(t.node_id, t.issued_at, t.target_ts).subscribe({
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
