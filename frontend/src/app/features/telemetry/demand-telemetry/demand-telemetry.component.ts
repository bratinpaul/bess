import { CommonModule } from '@angular/common';
import { Component, ElementRef, OnInit, ViewChild, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { map } from 'rxjs';

import {
  BulkDemandTelemetryResult,
  DemandTelemetry,
  DemandTelemetryInput,
  MeteringPoint
} from '../../../core/models/demand-telemetry.model';
import { DemandTelemetryService } from '../../../core/services/demand-telemetry.service';
import { GraphEntity, SeriesLoader, SeriesPoint } from '../graphs/chart-spec';
import { TelemetryGraphsComponent } from '../graphs/telemetry-graphs.component';
import { ColumnPickerComponent } from '../table/column-picker.component';
import { TableColumn, TableRow } from '../table/table-column';
import { TelemetryTableComponent } from '../table/telemetry-table.component';
import { DEMAND_CHARTS, DEMAND_TIMELINES } from './demand-chart-specs';
import { DEFAULT_DEMAND_COLUMN_KEYS, DEMAND_TABLE_COLUMNS } from './demand-table-columns';

const PAGE_SIZE_OPTIONS = [25, 50, 100];
const FROM_FILE = '';

interface EditState {
  mode: 'add' | 'edit';
  metering_point_id: number | null;
  ts: string; // datetime-local (plant time) in add mode; the stored ISO time in edit mode
  gross_load_kw: number | null;
  behind_meter_gen_kw: number | null;
  net_load_kw: number | null;
  load_reactive_kvar: number | null;
}

/** Live data feed -> Demand: site load at the metering points (gross, behind-the-meter generation, net, reactive),
 *  upload, add / edit / delete readings, tabular and graphical views. */
@Component({
  selector: 'app-demand-telemetry',
  standalone: true,
  imports: [CommonModule, FormsModule, TelemetryGraphsComponent, ColumnPickerComponent, TelemetryTableComponent],
  templateUrl: './demand-telemetry.component.html',
  styleUrl: './demand-telemetry.component.scss'
})
export class DemandTelemetryComponent implements OnInit {
  private route = inject(ActivatedRoute);
  private router = inject(Router);
  @ViewChild('fileInput') fileInput?: ElementRef<HTMLInputElement>;

  points: MeteringPoint[] = [];

  // upload
  showUpload = false;
  selectedFile: File | null = null;
  uploadCode = FROM_FILE;
  uploading = false;
  uploadResult: BulkDemandTelemetryResult | null = null;
  uploadError: string | null = null;
  showAllUploadErrors = false;

  // table
  readonly allColumns = DEMAND_TABLE_COLUMNS;
  readonly defaultColumnKeys = DEFAULT_DEMAND_COLUMN_KEYS;
  visibleColumns: TableColumn[] = DEMAND_TABLE_COLUMNS;
  rows: DemandTelemetry[] = [];
  tableRows: TableRow[] = [];
  total = 0;
  loading = true;
  error: string | null = null;
  filterPointId = '';
  filterStart = '';
  filterEnd = '';
  pageSizeOptions = PAGE_SIZE_OPTIONS;
  pageSize = PAGE_SIZE_OPTIONS[0];
  currentPage = 1;

  activeTab: 'tabular' | 'graphical' = 'tabular';

  // graphs
  readonly graphCharts = DEMAND_CHARTS;
  readonly graphTimelines = DEMAND_TIMELINES;
  graphEntities: GraphEntity[] = [];
  readonly loadGraphSeries: SeriesLoader = (id, start, end) =>
    this.service.series(Number(id), start, end).pipe(
      map((s) => ({
        entityName: s.mp_code,
        start: s.start,
        end: s.end,
        bucketSeconds: s.bucket_seconds,
        rawIntervalSeconds: s.raw_interval_seconds,
        points: s.points as SeriesPoint[],
        timelines: s.timelines,
        refs: { peakNet: s.refs['peak_net_kw'], billingPeak: s.refs['billing_peak_kw'], ratchet: s.refs['ratchet_kw'] }
      }))
    );

  // add / edit / delete
  edit: EditState | null = null;
  saving = false;
  editError: string | null = null;
  toDelete: DemandTelemetry | null = null;
  deleting = false;
  deleteError: string | null = null;

  constructor(private service: DemandTelemetryService) {}

  ngOnInit(): void {
    if (this.route.snapshot.queryParamMap.get('view') === 'graphical') {
      this.activeTab = 'graphical';
    }
    const mp = this.route.snapshot.queryParamMap.get('mp');
    if (mp && /^\d+$/.test(mp)) {
      this.filterPointId = mp;
    }
    this.loadPoints();
    this.fetchRows();
  }

  private loadPoints(): void {
    this.service.lookups().subscribe({
      next: (points) => {
        this.points = points;
        this.graphEntities = points.map((p) => ({ id: String(p.metering_point_id), name: `${p.mp_code} · ${p.site_name ?? ''}` }));
      },
      error: () => (this.error = 'Could not load the metering points. Is the backend running?')
    });
  }

  setTab(tab: 'tabular' | 'graphical'): void {
    this.activeTab = tab;
    this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { view: tab === 'graphical' ? 'graphical' : null },
      queryParamsHandling: 'merge',
      replaceUrl: true
    });
  }

  pointLabel(p: MeteringPoint): string {
    return `${p.mp_code} · ${p.site_name ?? 'site ' + p.site_id} · ${p.mp_type}${p.voltage_kv ? ' · ' + p.voltage_kv + ' kV' : ''}`;
  }

  // ---------------------------------------------------------------- table

  get totalPages(): number {
    return Math.max(1, Math.ceil(this.total / this.pageSize));
  }

  get rangeStart(): number {
    return this.total === 0 ? 0 : (this.currentPage - 1) * this.pageSize + 1;
  }

  get rangeEnd(): number {
    return Math.min(this.currentPage * this.pageSize, this.total);
  }

  fetchRows(): void {
    this.loading = true;
    this.error = null;
    this.service
      .list({
        meteringPointId: this.filterPointId ? Number(this.filterPointId) : undefined,
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
          this.error = 'Could not load demand readings. Is the backend running?';
          this.loading = false;
        }
      });
  }

  applyFilters(): void {
    this.currentPage = 1;
    this.fetchRows();
  }

  clearFilters(): void {
    this.filterPointId = '';
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
    this.service.bulkUpload(this.selectedFile, this.uploadCode || null).subscribe({
      next: (result) => {
        this.uploadResult = result;
        this.uploading = false;
        this.selectedFile = null;
        if (this.fileInput) {
          this.fileInput.nativeElement.value = '';
        }
        this.currentPage = 1;
        this.fetchRows();
        this.loadPoints();
      },
      error: (err) => {
        this.uploadError = err?.error?.detail || 'Upload failed. Is the backend running?';
        this.uploading = false;
      }
    });
  }

  // ---------------------------------------------------------------- add / edit / delete

  openAdd(): void {
    const now = new Date(Date.now() + 330 * 60e3).toISOString().slice(0, 16);
    this.editError = null;
    this.edit = {
      mode: 'add',
      metering_point_id: this.filterPointId ? Number(this.filterPointId) : this.points[0]?.metering_point_id ?? null,
      ts: now,
      gross_load_kw: null,
      behind_meter_gen_kw: 0,
      net_load_kw: null,
      load_reactive_kvar: null
    };
  }

  openEdit(row: TableRow): void {
    const r = row as unknown as DemandTelemetry;
    const num = (v: unknown) => (v === null || v === undefined || v === '' ? null : Number(v));
    this.editError = null;
    this.edit = {
      mode: 'edit',
      metering_point_id: r.metering_point_id,
      ts: r.ts,
      gross_load_kw: num(r.gross_load_kw),
      behind_meter_gen_kw: num(r.behind_meter_gen_kw),
      net_load_kw: num(r.net_load_kw),
      load_reactive_kvar: num(r.load_reactive_kvar)
    };
  }

  /** net = gross - behind-the-meter generation, filled in as the user types. */
  syncNet(): void {
    const e = this.edit;
    if (e && e.gross_load_kw !== null && (e.gross_load_kw as unknown) !== '') {
      e.net_load_kw = Math.round((Number(e.gross_load_kw) - Number(e.behind_meter_gen_kw || 0)) * 100) / 100;
    }
  }

  get editProblem(): string | null {
    const e = this.edit;
    if (!e) {
      return null;
    }
    if (!e.metering_point_id) {
      return 'Choose a metering point';
    }
    if (!e.ts) {
      return 'Enter the time';
    }
    if ((e.gross_load_kw === null || (e.gross_load_kw as unknown) === '') && (e.net_load_kw === null || (e.net_load_kw as unknown) === '')) {
      return 'Enter the gross or the net load';
    }
    if (Number(e.gross_load_kw) < 0 || Number(e.behind_meter_gen_kw) < 0) {
      return 'Load and generation can’t be negative';
    }
    return null;
  }

  save(): void {
    const e = this.edit;
    if (!e || this.editProblem) {
      return;
    }
    const val = (v: number | null) => (v === null || (v as unknown) === '' ? null : Number(v));
    const body: DemandTelemetryInput = {
      gross_load_kw: val(e.gross_load_kw),
      behind_meter_gen_kw: val(e.behind_meter_gen_kw),
      net_load_kw: val(e.net_load_kw),
      load_reactive_kvar: val(e.load_reactive_kvar)
    };
    this.saving = true;
    this.editError = null;
    const req$ =
      e.mode === 'add'
        ? this.service.add({ ...body, metering_point_id: e.metering_point_id!, ts: e.ts + ':00+05:30' })
        : this.service.update(e.metering_point_id!, e.ts, body);
    req$.subscribe({
      next: () => {
        this.saving = false;
        this.edit = null;
        this.fetchRows();
        this.loadPoints();
      },
      error: (err) => {
        this.saving = false;
        const d = err?.error?.detail;
        this.editError = Array.isArray(d) ? d.map((x: { msg: string }) => x.msg.replace(/^Value error, /, '')).join('; ') : d || 'Saving failed.';
      }
    });
  }

  confirmDelete(row: TableRow): void {
    this.deleteError = null;
    this.toDelete = row as unknown as DemandTelemetry;
  }

  deleteConfirmed(): void {
    const t = this.toDelete;
    if (!t) {
      return;
    }
    this.deleting = true;
    this.service.delete(t.metering_point_id, t.ts).subscribe({
      next: () => {
        this.deleting = false;
        this.toDelete = null;
        this.fetchRows();
        this.loadPoints();
      },
      error: (err) => {
        this.deleting = false;
        this.deleteError = err?.error?.detail || 'Deleting failed.';
      }
    });
  }
}
