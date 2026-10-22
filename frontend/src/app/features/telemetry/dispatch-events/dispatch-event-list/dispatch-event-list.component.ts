import { CommonModule } from '@angular/common';
import { Component, ElementRef, OnDestroy, OnInit, ViewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';

import {
  BulkDispatchEventResult,
  DispatchEvent,
  DispatchEventAnalytics,
  DispatchEventFilters,
  DispatchEventLookups,
  DispatchEventStats,
  DispatchStatus,
  MODE_ORDER,
  modeLabel,
  plantTime
} from '../../../../core/models/dispatch-event.model';
import { DispatchEventService } from '../../../../core/services/dispatch-event.service';
import { ColumnPickerComponent } from '../../table/column-picker.component';
import { TableColumn } from '../../table/table-column';
import { DispatchEventGraphsComponent, DISPATCH_CHART_OPTIONS } from '../dispatch-event-graphs/dispatch-event-graphs.component';
import { ChartSelectorComponent } from '../../graphs/chart-selector.component';
import { DISPATCH_DEFAULT_COLUMN_KEYS, DISPATCH_TABLE_COLUMNS } from './dispatch-table-columns';

const PAGE_SIZE_OPTIONS = [25, 50, 100];

@Component({
  selector: 'app-dispatch-event-list',
  standalone: true,
  imports: [CommonModule, FormsModule, DispatchEventGraphsComponent, ColumnPickerComponent, ChartSelectorComponent],
  templateUrl: './dispatch-event-list.component.html',
  styleUrl: './dispatch-event-list.component.scss'
})
export class DispatchEventListComponent implements OnInit, OnDestroy {
  @ViewChild('fileInput') fileInput?: ElementRef<HTMLInputElement>;

  items: DispatchEvent[] = [];
  total = 0;
  stats: DispatchEventStats | null = null;
  loading = true;
  error: string | null = null;

  lookups: DispatchEventLookups | null = null;

  // column selector (same as the other telemetry tables)
  allColumns = DISPATCH_TABLE_COLUMNS;
  defaultColumnKeys = DISPATCH_DEFAULT_COLUMN_KEYS;
  visibleColumns: TableColumn[] = DISPATCH_TABLE_COLUMNS.filter((c) => DISPATCH_DEFAULT_COLUMN_KEYS.includes(c.key));

  activeTab: 'tabular' | 'graphical' = 'tabular';
  chartOptions = DISPATCH_CHART_OPTIONS;
  hiddenCharts = new Set<string>();
  analytics: DispatchEventAnalytics | null = null;
  analyticsLoading = false;
  analyticsError: string | null = null;
  /** Filters the loaded analytics belong to; they are refetched only when these change. */
  private analyticsKey: string | null = null;
  plantTime = plantTime;
  modeLabel = modeLabel;

  // filters (server side)
  mode = '';
  gridService = '';
  command = '';
  source = '';
  status: DispatchStatus | '' = '';
  accepted: boolean | null = null;
  emsId: number | null = null;
  start = '';
  end = '';
  search = '';
  private searchTimer?: ReturnType<typeof setTimeout>;

  pageSizeOptions = PAGE_SIZE_OPTIONS;
  pageSize = PAGE_SIZE_OPTIONS[0];
  currentPage = 1;

  itemToDelete: DispatchEvent | null = null;
  deleting = false;
  deleteError: string | null = null;

  // bulk load
  /** The upload section is hidden until the header switch turns it on. */
  showUpload = false;
  selectedFile: File | null = null;
  uploading = false;
  uploadResult: BulkDispatchEventResult | null = null;
  uploadError: string | null = null;
  showAllUploadErrors = false;

  constructor(
    private service: DispatchEventService,
    private route: ActivatedRoute,
    private router: Router
  ) {}

  ngOnInit(): void {
    // ?ems= / ?mode= / ?status=Active, e.g. from other pages
    const params = this.route.snapshot.queryParamMap;
    const ems = Number(params.get('ems'));
    this.emsId = ems > 0 ? ems : null;
    this.mode = (params.get('mode') || '').toUpperCase();
    const status = params.get('status');
    this.status = status === 'Active' || status === 'Completed' || status === 'Aborted' ? status : '';
    if (params.get('view') === 'graphical') {
      this.activeTab = 'graphical';
    }

    this.service.lookups().subscribe({
      next: (lookups) => (this.lookups = lookups),
      error: () => {
        /* filters still work without the lookups */
      }
    });
    this.fetch();
  }

  ngOnDestroy(): void {
    clearTimeout(this.searchTimer);
  }

  /** Only the newest request may update the page; a slower, older response is dropped. */
  private requestSeq = 0;

  private get filters(): DispatchEventFilters {
    return {
      dispatch_mode: this.mode,
      grid_service: this.gridService,
      command_code: this.command,
      source: this.source,
      status: this.status,
      accepted: this.accepted,
      ems_id: this.emsId,
      start: this.start,
      end: this.end,
      q: this.search.trim()
    };
  }

  fetch(): void {
    const seq = ++this.requestSeq;
    this.loading = true;
    this.error = null;
    if (this.activeTab === 'graphical') {
      this.fetchAnalytics();
    }
    this.service
      .list({ ...this.filters, page: this.currentPage, page_size: this.pageSize })
      .subscribe({
        next: (page) => {
          if (seq !== this.requestSeq) {
            return;
          }
          this.items = page.items;
          this.total = page.total;
          this.stats = page.stats;
          this.loading = false;
        },
        error: () => {
          if (seq !== this.requestSeq) {
            return;
          }
          this.error = 'Could not load dispatch events. Is the backend running?';
          this.loading = false;
        }
      });
  }

  /** Loads the graphical tab's aggregates for the current filters (skipped when already loaded). */
  fetchAnalytics(): void {
    const key = JSON.stringify(this.filters);
    if (key === this.analyticsKey) {
      return;
    }
    this.analyticsKey = key;
    this.analyticsLoading = true;
    this.analyticsError = null;
    this.service.analytics(this.filters).subscribe({
      next: (analytics) => {
        // ignore a response for filters that have since changed
        if (key === this.analyticsKey) {
          this.analytics = analytics;
          this.analyticsLoading = false;
        }
      },
      error: () => {
        if (key === this.analyticsKey) {
          this.analyticsError = 'Could not load the graphs. Is the backend running?';
          this.analyticsLoading = false;
          this.analyticsKey = null;
        }
      }
    });
  }

  setTab(tab: 'tabular' | 'graphical'): void {
    this.activeTab = tab;
    if (tab === 'graphical') {
      this.fetchAnalytics();
    }
    // keep the tab in the URL so it survives a reload and can be bookmarked
    this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { view: tab === 'graphical' ? 'graphical' : null },
      queryParamsHandling: 'merge',
      replaceUrl: true
    });
  }

  // chart clicks narrow the filters (and so both tabs)
  filterByDay(day: string): void {
    this.start = day;
    this.end = day;
    this.applyFilters();
  }

  toggleGridService(service: string): void {
    this.gridService = this.gridService === service ? '' : service;
    this.applyFilters();
  }

  openDispatch(dispatchId: string): void {
    this.router.navigate(['/telemetry/dispatch', dispatchId]);
  }

  applyFilters(): void {
    this.currentPage = 1;
    this.fetch();
  }

  onSearchChange(): void {
    clearTimeout(this.searchTimer);
    this.searchTimer = setTimeout(() => this.applyFilters(), 300);
  }

  setMode(mode: string): void {
    this.mode = mode;
    this.applyFilters();
  }

  toggleStatus(status: DispatchStatus): void {
    this.status = this.status === status ? '' : status;
    this.applyFilters();
  }

  /** Mode tabs in a fixed order, then any other mode in master data. */
  get modeTabs(): string[] {
    const known = (this.lookups?.modes ?? []).map((m) => m.code);
    return [...MODE_ORDER.filter((m) => !known.length || known.includes(m)), ...known.filter((m) => !MODE_ORDER.includes(m))];
  }

  get hasFilters(): boolean {
    return !!(this.mode || this.gridService || this.command || this.source || this.status || this.accepted !== null ||
      this.emsId !== null || this.start || this.end || this.search.trim());
  }

  clearFilters(): void {
    this.mode = '';
    this.gridService = '';
    this.command = '';
    this.source = '';
    this.status = '';
    this.accepted = null;
    this.emsId = null;
    this.start = '';
    this.end = '';
    this.search = '';
    this.applyFilters();
  }

  // ---------------------------------------------------------------- paging

  get totalPages(): number {
    return Math.max(1, Math.ceil(this.total / this.pageSize));
  }

  get rangeStart(): number {
    return this.total === 0 ? 0 : (this.currentPage - 1) * this.pageSize + 1;
  }

  get rangeEnd(): number {
    return Math.min(this.currentPage * this.pageSize, this.total);
  }

  setPageSize(size: number): void {
    this.pageSize = size;
    this.applyFilters();
  }

  goToPage(page: number): void {
    if (page >= 1 && page <= this.totalPages) {
      this.currentPage = page;
      this.fetch();
    }
  }

  // ---------------------------------------------------------------- display

  num(value: string | number | null | undefined): number | null {
    return value === null || value === undefined || value === '' ? null : Number(value);
  }

  formatDuration(minutes: number | null): string {
    if (minutes === null) {
      return '';
    }
    if (minutes < 60) {
      return `${Math.round(minutes)} min`;
    }
    const h = Math.floor(minutes / 60);
    const m = Math.round(minutes % 60);
    return m ? `${h} h ${m} min` : `${h} h`;
  }

  /** "01:35", or the full date when the window crosses midnight. */
  endLabel(item: DispatchEvent): string {
    if (!item.effective_to) {
      return '';
    }
    return item.effective_to.slice(0, 10) === item.effective_from.slice(0, 10)
      ? item.effective_to.slice(11, 16)
      : plantTime(item.effective_to);
  }

  /** Setpoint magnitude; the direction is shown in words. */
  absKw(item: DispatchEvent): number {
    return Math.abs(Number(item.p_setpoint_kw));
  }

  direction(item: DispatchEvent): 'charge' | 'discharge' | 'none' {
    const p = Number(item.p_setpoint_kw);
    return p > 0 ? 'charge' : p < 0 ? 'discharge' : 'none';
  }

  /** Plain value for the columns without a custom cell. */
  cell(item: DispatchEvent, column: TableColumn): string {
    const value = (item as unknown as Record<string, unknown>)[column.key];
    if (value === null || value === undefined || value === '') {
      return '—';
    }
    if (column.kind === 'timestamp') {
      return plantTime(String(value));
    }
    if (column.kind === 'number') {
      return Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 });
    }
    return String(value);
  }

  // ---------------------------------------------------------------- row actions

  view(item: DispatchEvent): void {
    this.router.navigate(['/telemetry/dispatch', item.dispatch_id]);
  }

  edit(item: DispatchEvent, event: Event): void {
    event.stopPropagation();
    this.router.navigate(['/telemetry/dispatch', item.dispatch_id, 'edit']);
  }

  confirmDelete(item: DispatchEvent, event: Event): void {
    event.stopPropagation();
    this.deleteError = null;
    this.itemToDelete = item;
  }

  deleteConfirmed(): void {
    const target = this.itemToDelete;
    if (!target) {
      return;
    }
    this.deleting = true;
    this.service.delete(target.dispatch_id).subscribe({
      next: () => {
        this.itemToDelete = null;
        this.deleting = false;
        this.analyticsKey = null;
        this.fetch();
      },
      error: (err) => {
        this.deleteError = err?.error?.detail || 'Failed to delete the dispatch.';
        this.deleting = false;
      }
    });
  }

  // ---------------------------------------------------------------- bulk load

  onFileSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    this.selectedFile = input.files?.[0] ?? null;
    this.uploadResult = null;
    this.uploadError = null;
    this.showAllUploadErrors = false;
  }

  get visibleUploadErrors() {
    if (!this.uploadResult) {
      return [];
    }
    return this.showAllUploadErrors ? this.uploadResult.errors : this.uploadResult.errors.slice(0, 10);
  }

  upload(): void {
    if (!this.selectedFile) {
      return;
    }
    this.uploading = true;
    this.uploadError = null;
    this.uploadResult = null;
    this.service.bulkUpload(this.selectedFile).subscribe({
      next: (result) => {
        this.uploadResult = result;
        this.uploading = false;
        this.selectedFile = null;
        if (this.fileInput) {
          this.fileInput.nativeElement.value = '';
        }
        this.analyticsKey = null;
        this.fetch();
      },
      error: (err) => {
        this.uploadError = err?.error?.detail || 'Upload failed. Is the backend running?';
        this.uploading = false;
      }
    });
  }
}
