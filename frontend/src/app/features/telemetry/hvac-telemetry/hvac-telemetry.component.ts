import { CommonModule } from '@angular/common';
import { Component, OnInit, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { map } from 'rxjs';

import {
  BulkHvacTelemetryResult,
  HvacUnit,
  HvacTelemetry,
  HvacTelemetryLookups
} from '../../../core/models/hvac-telemetry.model';
import { HvacTelemetryService } from '../../../core/services/hvac-telemetry.service';
import { GraphEntity, SeriesLoader, SeriesPoint } from '../graphs/chart-spec';
import { TelemetryGraphsComponent } from '../graphs/telemetry-graphs.component';
import { ColumnPickerComponent } from '../table/column-picker.component';
import { TableColumn, TableRow } from '../table/table-column';
import { TelemetryTableComponent } from '../table/telemetry-table.component';
import { HVAC_CHARTS, HVAC_TIMELINES } from './hvac-chart-specs';
import { DEFAULT_HVAC_COLUMN_KEYS, HVAC_TABLE_COLUMNS } from './hvac-table-columns';

const PAGE_SIZE_OPTIONS = [25, 50, 100];

@Component({
  selector: 'app-hvac-telemetry',
  standalone: true,
  imports: [CommonModule, FormsModule, TelemetryGraphsComponent, ColumnPickerComponent, TelemetryTableComponent],
  templateUrl: './hvac-telemetry.component.html',
  styleUrl: './hvac-telemetry.component.scss'
})
export class HvacTelemetryComponent implements OnInit {
  private route = inject(ActivatedRoute);
  private router = inject(Router);

  units: HvacUnit[] = [];
  lookups: HvacTelemetryLookups = { units: [], cooling_modes: [] };

  // Upload
  /** The upload section is hidden until the header switch turns it on. */
  showUpload = false;
  selectedFile: File | null = null;
  uploadHvacCode = '';
  uploading = false;
  uploadResult: BulkHvacTelemetryResult | null = null;
  uploadError: string | null = null;
  showAllUploadErrors = false;

  // View table
  // Column selector
  readonly allColumns = HVAC_TABLE_COLUMNS;
  readonly defaultColumnKeys = DEFAULT_HVAC_COLUMN_KEYS;
  visibleColumns: TableColumn[] = HVAC_TABLE_COLUMNS.filter((c) => DEFAULT_HVAC_COLUMN_KEYS.includes(c.key));

  rows: HvacTelemetry[] = [];
  tableRows: TableRow[] = [];
  total = 0;
  loading = true;
  error: string | null = null;

  filterHvacId = '';

  activeTab: 'tabular' | 'graphical' = 'tabular';

  // Graphical tab
  readonly graphCharts = HVAC_CHARTS;
  readonly graphTimelines = HVAC_TIMELINES;
  graphEntities: GraphEntity[] = [];
  readonly loadGraphSeries: SeriesLoader = (id, start, end) =>
    this.telemetryService.series(Number(id), start, end).pipe(
      map((s) => ({
        entityName: s.hvac_code,
        start: s.start,
        end: s.end,
        bucketSeconds: s.bucket_seconds,
        rawIntervalSeconds: s.raw_interval_seconds,
        points: s.points as SeriesPoint[],
        timelines: s.timelines,
        refs: { coolantSetpoint: s.coolant_setpoint_c }
      }))
    );
  filterStart = '';
  filterEnd = '';

  pageSizeOptions = PAGE_SIZE_OPTIONS;
  pageSize = PAGE_SIZE_OPTIONS[0];
  currentPage = 1;

  constructor(private telemetryService: HvacTelemetryService) {}

  setTab(tab: 'tabular' | 'graphical'): void {
    this.activeTab = tab;
    // keep the tab in the URL so it survives a reload and can be bookmarked
    this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { view: tab === 'graphical' ? 'graphical' : null },
      queryParamsHandling: 'merge',
      replaceUrl: true
    });
  }

  ngOnInit(): void {
    if (this.route.snapshot.queryParamMap.get('view') === 'graphical') {
      this.activeTab = 'graphical';
    }
    // ?hvac=<id> (e.g. from the HVAC pages) filters the table and seeds the graphs
    const hvac = this.route.snapshot.queryParamMap.get('hvac');
    if (hvac && /^\d+$/.test(hvac)) {
      this.filterHvacId = hvac;
    }
    this.telemetryService.lookups().subscribe({
      next: (lookups) => {
        this.lookups = lookups;
        this.units = lookups.units;
        this.graphEntities = lookups.units.map((u) => ({ id: String(u.hvac_id), name: u.hvac_code }));
        if (lookups.units.length > 0 && !this.uploadHvacCode) {
          this.uploadHvacCode = lookups.units[0].hvac_code;
        }
      },
      error: () => {
        this.error = 'Could not load HVAC units. Is the backend running?';
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
        hvacId: this.filterHvacId ? Number(this.filterHvacId) : undefined,
        start: this.filterStart || undefined,
        end: this.filterEnd || undefined,
        page: this.currentPage,
        pageSize: this.pageSize
      })
      .subscribe({
        next: (page) => {
          this.rows = page.items;
          this.tableRows = page.items as unknown as TableRow[];
          this.total = page.total;
          this.loading = false;
        },
        error: () => {
          this.error = 'Could not load HVAC telemetry. Is the backend running?';
          this.loading = false;
        }
      });
  }

  applyFilters(): void {
    this.currentPage = 1;
    this.fetchRows();
  }

  clearFilters(): void {
    this.filterHvacId = '';
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
    if (!this.selectedFile || !this.uploadHvacCode) {
      return;
    }
    this.uploading = true;
    this.uploadError = null;
    this.uploadResult = null;
    this.telemetryService.bulkUpload(this.selectedFile, this.uploadHvacCode).subscribe({
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
