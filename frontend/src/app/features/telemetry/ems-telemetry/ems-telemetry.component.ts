import { CommonModule } from '@angular/common';
import { Component, OnInit, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { map } from 'rxjs';

import {
  BulkEmsTelemetryResult,
  EmsController,
  EmsTelemetry,
  EmsTelemetryLookups
} from '../../../core/models/ems-telemetry.model';
import { EmsTelemetryService } from '../../../core/services/ems-telemetry.service';
import { GraphEntity, SeriesLoader, SeriesPoint } from '../graphs/chart-spec';
import { TelemetryGraphsComponent } from '../graphs/telemetry-graphs.component';
import { ColumnPickerComponent } from '../table/column-picker.component';
import { TableColumn, TableRow } from '../table/table-column';
import { TelemetryTableComponent } from '../table/telemetry-table.component';
import { EMS_CHARTS, EMS_TIMELINES } from './ems-chart-specs';
import { DEFAULT_EMS_COLUMN_KEYS, EMS_TABLE_COLUMNS } from './ems-table-columns';
import { EMS_KPI_DOMAIN } from '../../../core/models/kpi.model';
import { KpiAnalyticsComponent } from '../kpi-analytics/kpi-analytics.component';

type EmsTab = 'tabular' | 'graphical' | 'analytics';

const PAGE_SIZE_OPTIONS = [25, 50, 100];

@Component({
  selector: 'app-ems-telemetry',
  standalone: true,
  imports: [CommonModule, FormsModule, TelemetryGraphsComponent, ColumnPickerComponent, TelemetryTableComponent, KpiAnalyticsComponent],
  templateUrl: './ems-telemetry.component.html',
  styleUrl: './ems-telemetry.component.scss'
})
export class EmsTelemetryComponent implements OnInit {
  private route = inject(ActivatedRoute);
  private router = inject(Router);

  controllers: EmsController[] = [];
  lookups: EmsTelemetryLookups = { controllers: [], dispatch_modes: [], grid_services: [] };

  // Upload
  /** The upload section is hidden until the header switch turns it on. */
  showUpload = false;
  selectedFile: File | null = null;
  uploadEmsCode = '';
  uploading = false;
  uploadResult: BulkEmsTelemetryResult | null = null;
  uploadError: string | null = null;
  showAllUploadErrors = false;

  // View table
  // Column selector
  readonly allColumns = EMS_TABLE_COLUMNS;
  readonly defaultColumnKeys = DEFAULT_EMS_COLUMN_KEYS;
  visibleColumns: TableColumn[] = EMS_TABLE_COLUMNS.filter((c) => DEFAULT_EMS_COLUMN_KEYS.includes(c.key));

  rows: EmsTelemetry[] = [];
  tableRows: TableRow[] = [];
  total = 0;
  loading = true;
  error: string | null = null;

  filterEmsId = '';

  activeTab: EmsTab = 'tabular';
  readonly kpiDomain = EMS_KPI_DOMAIN;

  // Graphical tab
  readonly graphCharts = EMS_CHARTS;
  readonly graphTimelines = EMS_TIMELINES;
  graphEntities: GraphEntity[] = [];
  readonly loadGraphSeries: SeriesLoader = (id, start, end) =>
    this.telemetryService.series(Number(id), start, end).pipe(
      map((s) => ({
        entityName: s.ems_code,
        start: s.start,
        end: s.end,
        bucketSeconds: s.bucket_seconds,
        rawIntervalSeconds: s.raw_interval_seconds,
        points: s.points as SeriesPoint[],
        timelines: s.timelines,
        refs: {}
      }))
    );
  filterStart = '';
  filterEnd = '';

  pageSizeOptions = PAGE_SIZE_OPTIONS;
  pageSize = PAGE_SIZE_OPTIONS[0];
  currentPage = 1;

  constructor(private telemetryService: EmsTelemetryService) {}

  setTab(tab: EmsTab): void {
    this.activeTab = tab;
    // keep the tab in the URL so it survives a reload and can be bookmarked
    this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { view: tab === 'tabular' ? null : tab },
      queryParamsHandling: 'merge',
      replaceUrl: true
    });
  }

  ngOnInit(): void {
    const view = this.route.snapshot.queryParamMap.get('view');
    if (view === 'graphical' || view === 'analytics') {
      this.activeTab = view;
    }
    // ?ems=<id> (e.g. from the EMS pages) filters the table and seeds the graphs
    const ems = this.route.snapshot.queryParamMap.get('ems');
    if (ems && /^\d+$/.test(ems)) {
      this.filterEmsId = ems;
    }
    this.telemetryService.lookups().subscribe({
      next: (lookups) => {
        this.lookups = lookups;
        this.controllers = lookups.controllers;
        this.graphEntities = lookups.controllers.map((c) => ({ id: String(c.ems_id), name: c.ems_code }));
        if (lookups.controllers.length > 0 && !this.uploadEmsCode) {
          this.uploadEmsCode = lookups.controllers[0].ems_code;
        }
      },
      error: () => {
        this.error = 'Could not load EMS controllers. Is the backend running?';
      }
    });
    this.fetchRows();
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
        emsId: this.filterEmsId ? Number(this.filterEmsId) : undefined,
        start: this.filterStart || undefined,
        end: this.filterEnd || undefined,
        page: this.currentPage,
        pageSize: this.pageSize
      })
      .subscribe({
        next: (page) => {
          this.rows = page.items;
          this.tableRows = page.items.map((r) => ({
            ...r,
            plant_available: r.plant_available === 1 ? 'Yes' : r.plant_available === 0 ? 'No' : null
          }));
          this.total = page.total;
          this.loading = false;
        },
        error: () => {
          this.error = 'Could not load EMS telemetry. Is the backend running?';
          this.loading = false;
        }
      });
  }

  applyFilters(): void {
    this.currentPage = 1;
    this.fetchRows();
  }

  clearFilters(): void {
    this.filterEmsId = '';
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
    if (!this.selectedFile || !this.uploadEmsCode) {
      return;
    }
    this.uploading = true;
    this.uploadError = null;
    this.uploadResult = null;
    this.telemetryService.bulkUpload(this.selectedFile, this.uploadEmsCode).subscribe({
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
