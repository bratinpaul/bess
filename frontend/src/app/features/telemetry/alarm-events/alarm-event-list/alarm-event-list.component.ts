import { CommonModule } from '@angular/common';
import { Component, ElementRef, OnDestroy, OnInit, ViewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';

import { ALARM_SOURCES } from '../../../../core/models/alarm-catalog.model';
import {
  AlarmEvent,
  AlarmEventAnalytics,
  AlarmEventFilters,
  AlarmEventLookups,
  AlarmEventStats,
  BulkAlarmEventResult,
  plantTime
} from '../../../../core/models/alarm-event.model';
import { AlarmEventService } from '../../../../core/services/alarm-event.service';
import { ColumnPickerComponent } from '../../table/column-picker.component';
import { TableColumn } from '../../table/table-column';
import { AlarmEventGraphsComponent, ALARM_CHART_OPTIONS } from '../alarm-event-graphs/alarm-event-graphs.component';
import { ChartSelectorComponent } from '../../graphs/chart-selector.component';
import { ALARM_DEFAULT_COLUMN_KEYS, ALARM_TABLE_COLUMNS } from './alarm-table-columns';

const PAGE_SIZE_OPTIONS = [25, 50, 100];

@Component({
  selector: 'app-alarm-event-list',
  standalone: true,
  imports: [CommonModule, FormsModule, AlarmEventGraphsComponent, ColumnPickerComponent, ChartSelectorComponent],
  templateUrl: './alarm-event-list.component.html',
  styleUrl: './alarm-event-list.component.scss'
})
export class AlarmEventListComponent implements OnInit, OnDestroy {
  @ViewChild('fileInput') fileInput?: ElementRef<HTMLInputElement>;

  items: AlarmEvent[] = [];
  total = 0;
  stats: AlarmEventStats | null = null;
  loading = true;
  error: string | null = null;

  lookups: AlarmEventLookups | null = null;

  // column selector (same as the other telemetry tables)
  allColumns = ALARM_TABLE_COLUMNS;
  defaultColumnKeys = ALARM_DEFAULT_COLUMN_KEYS;
  visibleColumns: TableColumn[] = ALARM_TABLE_COLUMNS.filter((c) => ALARM_DEFAULT_COLUMN_KEYS.includes(c.key));

  activeTab: 'tabular' | 'graphical' = 'tabular';
  chartOptions = ALARM_CHART_OPTIONS;
  hiddenCharts = new Set<string>();
  analytics: AlarmEventAnalytics | null = null;
  analyticsLoading = false;
  analyticsError: string | null = null;
  /** Filters the loaded analytics belong to; they are refetched only when these change. */
  private analyticsKey: string | null = null;
  sources = ALARM_SOURCES;
  plantTime = plantTime;

  // filters (server side)
  source = '';
  severityLevel: number | null = null;
  status: '' | 'active' | 'cleared' = '';
  acknowledged: boolean | null = null;
  systemId: number | null = null;
  start = '';
  end = '';
  search = '';
  private searchTimer?: ReturnType<typeof setTimeout>;

  pageSizeOptions = PAGE_SIZE_OPTIONS;
  pageSize = PAGE_SIZE_OPTIONS[0];
  currentPage = 1;

  itemToDelete: AlarmEvent | null = null;
  deleting = false;
  deleteError: string | null = null;

  // bulk load
  /** The upload section is hidden until the header switch turns it on. */
  showUpload = false;
  selectedFile: File | null = null;
  uploading = false;
  uploadResult: BulkAlarmEventResult | null = null;
  uploadError: string | null = null;
  showAllUploadErrors = false;

  constructor(
    private service: AlarmEventService,
    private route: ActivatedRoute,
    private router: Router
  ) {}

  ngOnInit(): void {
    // ?system= / ?source= / ?status=active, e.g. from other pages
    const params = this.route.snapshot.queryParamMap;
    const system = Number(params.get('system'));
    this.systemId = system > 0 ? system : null;
    const source = (params.get('source') || '').toUpperCase();
    this.source = (ALARM_SOURCES as string[]).includes(source) ? source : '';
    this.status = params.get('status') === 'active' ? 'active' : params.get('status') === 'cleared' ? 'cleared' : '';
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

  private get filters(): AlarmEventFilters {
    return {
      source: this.source,
      severity_level: this.severityLevel,
      status: this.status,
      acknowledged: this.acknowledged,
      battery_system_id: this.systemId,
      start: this.start,
      end: this.end,
      q: this.search.trim()
    };
  }

  /** Only the newest request may update the page; a slower, older response is dropped. */
  private requestSeq = 0;

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
          this.error = 'Could not load alarms. Is the backend running?';
          this.loading = false;
        }
      });
  }

  /** Loads the graphical tab's aggregates for the current filters (skipped when already loaded). */
  fetchAnalytics(force = false): void {
    const key = JSON.stringify(this.filters);
    if (!force && key === this.analyticsKey) {
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
  filterBySeverity(level: number): void {
    this.severityLevel = level;
    this.applyFilters();
  }

  filterByDay(day: string): void {
    this.start = day;
    this.end = day;
    this.applyFilters();
  }

  openAlarm(alarmId: string): void {
    this.router.navigate(['/telemetry/alarms', alarmId]);
  }

  applyFilters(): void {
    this.currentPage = 1;
    this.fetch();
  }

  onSearchChange(): void {
    clearTimeout(this.searchTimer);
    this.searchTimer = setTimeout(() => this.applyFilters(), 300);
  }

  setSource(source: string): void {
    this.source = source;
    this.applyFilters();
  }

  get hasFilters(): boolean {
    return !!(this.source || this.severityLevel !== null || this.status || this.acknowledged !== null ||
      this.systemId !== null || this.start || this.end || this.search.trim());
  }

  clearFilters(): void {
    this.source = '';
    this.severityLevel = null;
    this.status = '';
    this.acknowledged = null;
    this.systemId = null;
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

  /** Plain value for the columns without a custom cell. */
  cell(item: AlarmEvent, column: TableColumn): string {
    switch (column.key) {
      case 'end_time':
      case 'created_at':
      case 'updated_at':
        return plantTime(item[column.key]) || '—';
      case 'minutes_to_ack':
        return item.acknowledged_at
          ? this.formatDuration((Date.parse(item.acknowledged_at) - Date.parse(item.start_time)) / 60000)
          : '—';
    }
    const value = (item as unknown as Record<string, unknown>)[column.key];
    return value === null || value === undefined || value === '' ? '—' : String(value);
  }

  // ---------------------------------------------------------------- row actions

  view(item: AlarmEvent): void {
    this.router.navigate(['/telemetry/alarms', item.alarm_id]);
  }

  edit(item: AlarmEvent, event: Event): void {
    event.stopPropagation();
    this.router.navigate(['/telemetry/alarms', item.alarm_id, 'edit']);
  }

  confirmDelete(item: AlarmEvent, event: Event): void {
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
    this.service.delete(target.alarm_id).subscribe({
      next: () => {
        this.itemToDelete = null;
        this.deleting = false;
        this.analyticsKey = null;
        this.fetch();
      },
      error: (err) => {
        this.deleteError = err?.error?.detail || 'Failed to delete the alarm.';
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
