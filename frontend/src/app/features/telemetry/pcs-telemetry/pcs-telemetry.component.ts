import { CommonModule } from '@angular/common';
import { Component, OnInit, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { map } from 'rxjs';

import { Pcs } from '../../../core/models/pcs.model';
import {
  BulkPcsTelemetryResult,
  PcsTelemetry,
  PcsTelemetryLookups
} from '../../../core/models/pcs-telemetry.model';
import { PcsService } from '../../../core/services/pcs.service';
import { PcsTelemetryService } from '../../../core/services/pcs-telemetry.service';
import { GraphEntity, SeriesLoader, SeriesPoint } from '../graphs/chart-spec';
import { TelemetryGraphsComponent } from '../graphs/telemetry-graphs.component';
import { ColumnPickerComponent } from '../table/column-picker.component';
import { TableColumn, TableRow } from '../table/table-column';
import { TelemetryTableComponent } from '../table/telemetry-table.component';
import { PCS_CHARTS, PCS_TIMELINES } from './pcs-chart-specs';
import { DEFAULT_PCS_COLUMN_KEYS, PCS_TABLE_COLUMNS } from './pcs-table-columns';
import { PCS_KPI_DOMAIN } from '../../../core/models/kpi.model';
import { KpiAnalyticsComponent } from '../kpi-analytics/kpi-analytics.component';

type PcsTab = 'tabular' | 'graphical' | 'analytics';

const PAGE_SIZE_OPTIONS = [25, 50, 100];

@Component({
  selector: 'app-pcs-telemetry',
  standalone: true,
  imports: [CommonModule, FormsModule, TelemetryGraphsComponent, ColumnPickerComponent, TelemetryTableComponent, KpiAnalyticsComponent],
  templateUrl: './pcs-telemetry.component.html',
  styleUrl: './pcs-telemetry.component.scss'
})
export class PcsTelemetryComponent implements OnInit {
  private route = inject(ActivatedRoute);
  private router = inject(Router);

  pcsUnits: Pcs[] = [];
  lookups: PcsTelemetryLookups = { modes: [], grid_services: [], breaker_states: [] };

  // Upload
  /** The upload section is hidden until the header switch turns it on. */
  showUpload = false;
  selectedFile: File | null = null;
  uploading = false;
  uploadResult: BulkPcsTelemetryResult | null = null;
  uploadError: string | null = null;
  showAllUploadErrors = false;

  activeTab: PcsTab = 'tabular';
  readonly kpiDomain = PCS_KPI_DOMAIN;

  // Graphical tab
  readonly graphCharts = PCS_CHARTS;
  readonly graphTimelines = PCS_TIMELINES;
  graphEntities: GraphEntity[] = [];
  readonly loadGraphSeries: SeriesLoader = (id, start, end) =>
    this.telemetryService.series(id, start, end).pipe(
      map((s) => ({
        entityName: s.pcs_code,
        start: s.start,
        end: s.end,
        bucketSeconds: s.bucket_seconds,
        rawIntervalSeconds: s.raw_interval_seconds,
        points: s.points as SeriesPoint[],
        timelines: s.timelines,
        refs: { minPowerFactor: s.min_power_factor, ratedApparentKva: s.rated_apparent_kva }
      }))
    );

  // Column selector
  readonly allColumns = PCS_TABLE_COLUMNS;
  readonly defaultColumnKeys = DEFAULT_PCS_COLUMN_KEYS;
  visibleColumns: TableColumn[] = PCS_TABLE_COLUMNS.filter((c) => DEFAULT_PCS_COLUMN_KEYS.includes(c.key));

  // View table
  rows: PcsTelemetry[] = [];
  total = 0;
  loading = true;
  error: string | null = null;

  filterPcsId = '';
  filterStart = '';
  filterEnd = '';

  pageSizeOptions = PAGE_SIZE_OPTIONS;
  pageSize = PAGE_SIZE_OPTIONS[0];
  currentPage = 1;

  constructor(
    private pcsService: PcsService,
    private telemetryService: PcsTelemetryService
  ) {}

  ngOnInit(): void {
    const view = this.route.snapshot.queryParamMap.get('view');
    if (view === 'graphical' || view === 'analytics') {
      this.activeTab = view;
    }
    // ?pcs=<id> (e.g. from the PCS pages) filters the table and seeds the graphs
    const pcs = this.route.snapshot.queryParamMap.get('pcs');
    if (pcs && /^\d+$/.test(pcs)) {
      this.filterPcsId = pcs;
    }
    this.pcsService.list().subscribe({
      next: (units) => {
        this.pcsUnits = units;
        this.graphEntities = units.map((u) => ({ id: String(u.pcs_id), name: u.pcs_code }));
      },
      error: () => {
        /* PCS dropdown is optional context; table still works without it */
      }
    });
    this.telemetryService.lookups().subscribe({
      next: (lookups) => (this.lookups = lookups),
      error: () => {}
    });
    this.fetchRows();
  }

  setTab(tab: PcsTab): void {
    this.activeTab = tab;
    // keep the tab in the URL so it survives a reload and can be bookmarked
    this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { view: tab === 'tabular' ? null : tab },
      queryParamsHandling: 'merge',
      replaceUrl: true
    });
  }

  get tableRows(): TableRow[] {
    return this.rows as unknown as TableRow[];
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
        pcsId: this.filterPcsId ? Number(this.filterPcsId) : undefined,
        start: this.filterStart || undefined,
        end: this.filterEnd || undefined,
        page: this.currentPage,
        pageSize: this.pageSize
      })
      .subscribe({
        next: (page) => {
          this.rows = page.items;
          this.total = page.total;
          this.loading = false;
        },
        error: () => {
          this.error = 'Could not load PCS telemetry. Is the backend running?';
          this.loading = false;
        }
      });
  }

  applyFilters(): void {
    this.currentPage = 1;
    this.fetchRows();
  }

  clearFilters(): void {
    this.filterPcsId = '';
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
