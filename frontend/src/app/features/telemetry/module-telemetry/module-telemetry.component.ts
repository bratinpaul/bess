import { CommonModule } from '@angular/common';
import { Component, OnInit, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { map } from 'rxjs';

import {
  BulkModuleTelemetryResult,
  ModuleOption,
  ModuleTelemetry
} from '../../../core/models/module-telemetry.model';
import { ModuleTelemetryService } from '../../../core/services/module-telemetry.service';
import { GraphEntity, SeriesLoader, SeriesPoint } from '../graphs/chart-spec';
import { TelemetryGraphsComponent } from '../graphs/telemetry-graphs.component';
import { ColumnPickerComponent } from '../table/column-picker.component';
import { TableColumn, TableRow } from '../table/table-column';
import { TelemetryTableComponent } from '../table/telemetry-table.component';
import { MODULE_CHARTS } from './module-chart-specs';
import { DEFAULT_MODULE_COLUMN_KEYS, MODULE_TABLE_COLUMNS } from './module-table-columns';

const PAGE_SIZE_OPTIONS = [25, 50, 100];

@Component({
  selector: 'app-module-telemetry',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    ColumnPickerComponent,
    TelemetryTableComponent,
    TelemetryGraphsComponent
  ],
  templateUrl: './module-telemetry.component.html',
  styleUrl: './module-telemetry.component.scss'
})
export class ModuleTelemetryComponent implements OnInit {
  private telemetryService = inject(ModuleTelemetryService);
  private route = inject(ActivatedRoute);
  private router = inject(Router);

  modules: ModuleOption[] = [];

  // Upload
  /** The Upload Telemetry File section is hidden until the header toggle turns it on. */
  showUpload = false;
  selectedFile: File | null = null;
  uploading = false;
  uploadResult: BulkModuleTelemetryResult | null = null;
  uploadError: string | null = null;
  showAllUploadErrors = false;

  activeTab: 'tabular' | 'graphical' = 'tabular';

  // Graphical tab
  readonly graphCharts = MODULE_CHARTS;
  graphEntities: GraphEntity[] = [];
  readonly loadGraphSeries: SeriesLoader = (id, start, end) =>
    this.telemetryService.series(Number(id), start, end).pipe(
      map((s) => ({
        entityName: s.serial_number,
        start: s.start,
        end: s.end,
        bucketSeconds: s.bucket_seconds,
        rawIntervalSeconds: s.raw_interval_seconds,
        points: s.points as SeriesPoint[],
        timelines: {},
        refs: {}
      }))
    );

  // Column selector
  readonly allColumns = MODULE_TABLE_COLUMNS;
  readonly defaultColumnKeys = DEFAULT_MODULE_COLUMN_KEYS;
  visibleColumns: TableColumn[] = MODULE_TABLE_COLUMNS;

  // View table
  rows: ModuleTelemetry[] = [];
  tableRows: TableRow[] = [];
  total = 0;
  loading = true;
  error: string | null = null;

  filterModuleId: number | null = null;
  filterStart = '';
  filterEnd = '';

  pageSizeOptions = PAGE_SIZE_OPTIONS;
  pageSize = PAGE_SIZE_OPTIONS[0];
  currentPage = 1;

  ngOnInit(): void {
    if (this.route.snapshot.queryParamMap.get('view') === 'graphical') {
      this.activeTab = 'graphical';
    }
    // ?module=<id> (e.g. from the module pages) filters the table and seeds the graphs
    const module = Number(this.route.snapshot.queryParamMap.get('module'));
    if (module > 0) {
      this.filterModuleId = module;
    }
    this.telemetryService.modules().subscribe({
      next: (modules) => {
        this.modules = modules;
        this.graphEntities = modules.map((m) => ({ id: String(m.module_id), name: this.moduleLabel(m) }));
      },
      error: () => {
        /* module dropdown is optional context; the table still works without it */
      }
    });
    this.fetchRows();
  }

  moduleLabel(m: ModuleOption): string {
    return m.serial_number || `Module ${m.module_id}`;
  }

  get graphInitialModuleId(): string {
    return this.filterModuleId === null ? '' : String(this.filterModuleId);
  }

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
        moduleId: this.filterModuleId ?? undefined,
        start: this.filterStart || undefined,
        end: this.filterEnd || undefined,
        page: this.currentPage,
        pageSize: this.pageSize
      })
      .subscribe({
        next: (page) => {
          this.rows = page.items;
          // show balancing as Yes/No in the table
          this.tableRows = page.items.map((r) => ({
            ...r,
            balancing_active: r.balancing_active === null ? null : r.balancing_active ? 'Yes' : 'No'
          }));
          this.total = page.total;
          this.loading = false;
        },
        error: () => {
          this.error = 'Could not load module telemetry. Is the backend running?';
          this.loading = false;
        }
      });
  }

  applyFilters(): void {
    this.currentPage = 1;
    this.fetchRows();
  }

  clearFilters(): void {
    this.filterModuleId = null;
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
