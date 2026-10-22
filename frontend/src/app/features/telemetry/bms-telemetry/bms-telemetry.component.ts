import { CommonModule } from '@angular/common';
import { Component, OnInit, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';

import { BatterySystem } from '../../../core/models/battery-system.model';
import {
  BulkTelemetryResult,
  SystemTelemetry
} from '../../../core/models/system-telemetry.model';
import { BatterySystemService } from '../../../core/services/battery-system.service';
import { SystemTelemetryService } from '../../../core/services/system-telemetry.service';
import { ColumnPickerComponent } from '../table/column-picker.component';
import { TableColumn, TableRow } from '../table/table-column';
import { TelemetryTableComponent } from '../table/telemetry-table.component';
import { BMS_TABLE_COLUMNS, DEFAULT_COLUMN_KEYS } from './bms-table-columns';
import { map } from 'rxjs';

import { GraphEntity, SeriesLoader, SeriesPoint } from '../graphs/chart-spec';
import { TelemetryGraphsComponent } from '../graphs/telemetry-graphs.component';
import { BMS_CHARTS, BMS_TIMELINES } from './bms-chart-specs';
import { BMS_KPI_DOMAIN } from '../../../core/models/kpi.model';
import { KpiAnalyticsComponent } from '../kpi-analytics/kpi-analytics.component';

const PAGE_SIZE_OPTIONS = [25, 50, 100];

type BmsTab = 'tabular' | 'graphical' | 'analytics';

@Component({
  selector: 'app-bms-telemetry',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    TelemetryGraphsComponent,
    ColumnPickerComponent,
    TelemetryTableComponent,
    KpiAnalyticsComponent
  ],
  templateUrl: './bms-telemetry.component.html',
  styleUrl: './bms-telemetry.component.scss'
})
export class BmsTelemetryComponent implements OnInit {
  readonly kpiDomain = BMS_KPI_DOMAIN;

  private route = inject(ActivatedRoute);
  private router = inject(Router);

  systems: BatterySystem[] = [];

  // Upload
  /** The Upload Telemetry File section is hidden until the header toggle turns it on. */
  showUpload = false;
  selectedFile: File | null = null;
  uploading = false;
  uploadResult: BulkTelemetryResult | null = null;
  uploadError: string | null = null;
  showAllUploadErrors = false;

  activeTab: BmsTab = 'tabular';

  // Graphical tab
  readonly graphCharts = BMS_CHARTS;
  readonly graphTimelines = BMS_TIMELINES;
  graphEntities: GraphEntity[] = [];
  readonly loadGraphSeries: SeriesLoader = (id, start, end) =>
    this.telemetryService.series(Number(id), start, end).pipe(
      map((s) => ({
        entityName: s.system_name,
        start: s.start,
        end: s.end,
        bucketSeconds: s.bucket_seconds,
        rawIntervalSeconds: s.raw_interval_seconds,
        points: s.points as unknown as SeriesPoint[],
        timelines: {
          contactor: { states: s.contactor_states, segments: s.contactor_segments },
          rest: { states: ['At rest', 'Active'], segments: s.rest_segments ?? [] }
        },
        refs: {}
      }))
    );

  // Column selector
  readonly allColumns = BMS_TABLE_COLUMNS;
  readonly defaultColumnKeys = DEFAULT_COLUMN_KEYS;
  visibleColumns: TableColumn[] = BMS_TABLE_COLUMNS.filter((c) => DEFAULT_COLUMN_KEYS.includes(c.key));

  // View table
  rows: SystemTelemetry[] = [];
  total = 0;
  loading = true;
  error: string | null = null;

  filterSystemId = '';
  filterStart = '';
  filterEnd = '';

  pageSizeOptions = PAGE_SIZE_OPTIONS;
  pageSize = PAGE_SIZE_OPTIONS[0];
  currentPage = 1;

  constructor(
    private batterySystemService: BatterySystemService,
    private telemetryService: SystemTelemetryService
  ) {}

  ngOnInit(): void {
    const view = this.route.snapshot.queryParamMap.get('view');
    if (view === 'graphical' || view === 'analytics') {
      this.activeTab = view;
    }
    // ?system=<id> (e.g. from the battery system pages) filters the table and seeds the graphs
    const system = this.route.snapshot.queryParamMap.get('system');
    if (system && /^\d+$/.test(system)) {
      this.filterSystemId = system;
    }
    this.batterySystemService.list().subscribe({
      next: (systems) => {
        this.systems = systems;
        this.graphEntities = systems.map((sys) => ({ id: String(sys.battery_system_id), name: sys.system_name }));
      },
      error: () => {
        /* system dropdown is optional context; table still works without it */
      }
    });
    this.fetchRows();
  }

  setTab(tab: BmsTab): void {
    this.activeTab = tab;
    // keep the tab in the URL so it survives a reload and can be bookmarked
    this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { view: tab === 'tabular' ? null : tab },
      queryParamsHandling: 'merge',
      replaceUrl: true
    });
  }

  /** Table rows: the readings with at_rest as a readable label (built once per page load). */
  tableRows: TableRow[] = [];

  private toTableRows(rows: SystemTelemetry[]): TableRow[] {
    return rows.map((r) => ({ ...r, at_rest_label: r.at_rest === null || r.at_rest === undefined ? null : r.at_rest ? 'Yes' : 'No' }) as unknown as TableRow);
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

  get visibleUploadErrors() {
    if (!this.uploadResult) {
      return [];
    }
    return this.showAllUploadErrors ? this.uploadResult.errors : this.uploadResult.errors.slice(0, 10);
  }

  fetchRows(): void {
    this.loading = true;
    this.error = null;
    this.telemetryService
      .list({
        systemId: this.filterSystemId ? Number(this.filterSystemId) : undefined,
        start: this.filterStart || undefined,
        end: this.filterEnd || undefined,
        page: this.currentPage,
        pageSize: this.pageSize
      })
      .subscribe({
        next: (page) => {
          this.rows = page.items;
          this.tableRows = this.toTableRows(page.items);
          this.total = page.total;
          this.loading = false;
        },
        error: () => {
          this.error = 'Could not load telemetry. Is the backend running?';
          this.loading = false;
        }
      });
  }

  applyFilters(): void {
    this.currentPage = 1;
    this.fetchRows();
  }

  clearFilters(): void {
    this.filterSystemId = '';
    this.filterStart = '';
    this.filterEnd = '';
    this.currentPage = 1;
    this.fetchRows();
  }

  setPageSize(size: number): void {
    this.pageSize = size;
    this.currentPage = 1;
    this.fetchRows();
  }

  goToPage(page: number): void {
    if (page < 1 || page > this.totalPages) {
      return;
    }
    this.currentPage = page;
    this.fetchRows();
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
    this.telemetryService.bulkUpload(this.selectedFile).subscribe({
      next: (result) => {
        this.uploadResult = result;
        this.uploading = false;
        this.selectedFile = null;
        this.currentPage = 1;
        this.fetchRows();
      },
      error: (err) => {
        this.uploadError = err?.error?.detail || 'Upload failed. Is the backend running?';
        this.uploading = false;
      }
    });
  }
}
