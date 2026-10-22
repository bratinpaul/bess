import { CommonModule } from '@angular/common';
import { Component, ElementRef, OnInit, ViewChild, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { map } from 'rxjs';

import { BulkWeatherResult, WeatherInput, WeatherReading, WeatherStation } from '../../../core/models/weather.model';
import { WeatherService } from '../../../core/services/weather.service';
import { GraphEntity, SeriesLoader, SeriesPoint } from '../graphs/chart-spec';
import { TelemetryGraphsComponent } from '../graphs/telemetry-graphs.component';
import { ColumnPickerComponent } from '../table/column-picker.component';
import { TableColumn, TableRow } from '../table/table-column';
import { TelemetryTableComponent } from '../table/telemetry-table.component';
import { WEATHER_CHARTS, WEATHER_TIMELINES } from './weather-chart-specs';
import { DEFAULT_WEATHER_COLUMN_KEYS, WEATHER_TABLE_COLUMNS } from './weather-table-columns';

const PAGE_SIZE_OPTIONS = [25, 50, 100];
const FROM_FILE = '';

interface EditState {
  mode: 'add' | 'edit';
  station_id: number | null;
  ts: string; // datetime-local (plant time) in add mode; the stored ISO time in edit mode
  temp_c: number | null;
  humidity_pct: number | null;
  ghi_wm2: number | null;
  cloud_fraction: number | null;
  wind_ms: number | null;
}

const VALUE_KEYS = ['temp_c', 'humidity_pct', 'ghi_wm2', 'cloud_fraction', 'wind_ms'] as const;
const LIMITS: Record<(typeof VALUE_KEYS)[number], [number, number, string]> = {
  temp_c: [-60, 65, 'Temperature'],
  humidity_pct: [0, 100, 'Humidity'],
  ghi_wm2: [0, 1500, 'GHI'],
  cloud_fraction: [0, 1, 'Cloud fraction'],
  wind_ms: [0, 80, 'Wind speed']
};

/** Live data feed -> Weather: measured weather at the stations (temperature, irradiance, humidity, wind, cloud),
 *  upload, add / edit / delete readings, tabular and graphical views. */
@Component({
  selector: 'app-weather',
  standalone: true,
  imports: [CommonModule, FormsModule, TelemetryGraphsComponent, ColumnPickerComponent, TelemetryTableComponent],
  templateUrl: './weather.component.html',
  styleUrl: './weather.component.scss'
})
export class WeatherComponent implements OnInit {
  private route = inject(ActivatedRoute);
  private router = inject(Router);
  @ViewChild('fileInput') fileInput?: ElementRef<HTMLInputElement>;

  stations: WeatherStation[] = [];

  // upload
  showUpload = false;
  selectedFile: File | null = null;
  uploadCode = FROM_FILE;
  uploading = false;
  uploadResult: BulkWeatherResult | null = null;
  uploadError: string | null = null;
  showAllUploadErrors = false;

  // table
  readonly allColumns = WEATHER_TABLE_COLUMNS;
  readonly defaultColumnKeys = DEFAULT_WEATHER_COLUMN_KEYS;
  visibleColumns: TableColumn[] = WEATHER_TABLE_COLUMNS;
  rows: WeatherReading[] = [];
  tableRows: TableRow[] = [];
  total = 0;
  loading = true;
  error: string | null = null;
  filterStationId = '';
  filterStart = '';
  filterEnd = '';
  pageSizeOptions = PAGE_SIZE_OPTIONS;
  pageSize = PAGE_SIZE_OPTIONS[0];
  currentPage = 1;

  activeTab: 'tabular' | 'graphical' = 'tabular';

  // graphs
  readonly graphCharts = WEATHER_CHARTS;
  readonly graphTimelines = WEATHER_TIMELINES;
  graphEntities: GraphEntity[] = [];
  readonly loadGraphSeries: SeriesLoader = (id, start, end) =>
    this.service.series(Number(id), start, end).pipe(
      map((s) => ({
        entityName: s.station_code,
        start: s.start,
        end: s.end,
        bucketSeconds: s.bucket_seconds,
        rawIntervalSeconds: s.raw_interval_seconds,
        points: s.points as SeriesPoint[],
        timelines: s.timelines,
        refs: { tempMax: s.refs['temp_max_c'], tempMin: s.refs['temp_min_c'], ghiMax: s.refs['ghi_max_wm2'] }
      }))
    );

  // add / edit / delete
  edit: EditState | null = null;
  saving = false;
  editError: string | null = null;
  toDelete: WeatherReading | null = null;
  deleting = false;
  deleteError: string | null = null;

  constructor(private service: WeatherService) {}

  ngOnInit(): void {
    if (this.route.snapshot.queryParamMap.get('view') === 'graphical') {
      this.activeTab = 'graphical';
    }
    const st = this.route.snapshot.queryParamMap.get('station');
    if (st && /^\d+$/.test(st)) {
      this.filterStationId = st;
    }
    this.loadStations();
    this.fetchRows();
  }

  private loadStations(): void {
    this.service.lookups().subscribe({
      next: (stations) => {
        this.stations = stations;
        this.graphEntities = stations.map((s) => ({ id: String(s.station_id), name: `${s.station_code} · ${s.site_name ?? ''}` }));
      },
      error: () => (this.error = 'Could not load the weather stations. Is the backend running?')
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

  stationLabel(s: WeatherStation): string {
    return `${s.station_code} · ${s.site_name ?? 'no site'}${s.provider ? ' · ' + s.provider : ''}`;
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
        stationId: this.filterStationId ? Number(this.filterStationId) : undefined,
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
          this.error = 'Could not load weather readings. Is the backend running?';
          this.loading = false;
        }
      });
  }

  applyFilters(): void {
    this.currentPage = 1;
    this.fetchRows();
  }

  clearFilters(): void {
    this.filterStationId = '';
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
        this.loadStations();
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
      station_id: this.filterStationId ? Number(this.filterStationId) : this.stations[0]?.station_id ?? null,
      ts: now,
      temp_c: null,
      humidity_pct: null,
      ghi_wm2: null,
      cloud_fraction: null,
      wind_ms: null
    };
  }

  openEdit(row: TableRow): void {
    const r = row as unknown as WeatherReading;
    const num = (v: unknown) => (v === null || v === undefined || v === '' ? null : Number(v));
    this.editError = null;
    this.edit = {
      mode: 'edit',
      station_id: r.station_id,
      ts: r.ts,
      temp_c: num(r.temp_c),
      humidity_pct: num(r.humidity_pct),
      ghi_wm2: num(r.ghi_wm2),
      cloud_fraction: num(r.cloud_fraction),
      wind_ms: num(r.wind_ms)
    };
  }

  private val(v: number | null | undefined): number | null {
    return v === null || v === undefined || (v as unknown) === '' ? null : Number(v);
  }

  get editProblem(): string | null {
    const e = this.edit;
    if (!e) {
      return null;
    }
    if (!e.station_id) {
      return 'Choose a weather station';
    }
    if (!e.ts) {
      return 'Enter the time';
    }
    if (VALUE_KEYS.every((k) => this.val(e[k]) === null)) {
      return 'Enter at least one weather value';
    }
    for (const k of VALUE_KEYS) {
      const v = this.val(e[k]);
      const [lo, hi, label] = LIMITS[k];
      if (v !== null && (v < lo || v > hi)) {
        return `${label} must be between ${lo} and ${hi}`;
      }
    }
    return null;
  }

  save(): void {
    const e = this.edit;
    if (!e || this.editProblem) {
      return;
    }
    const body: WeatherInput = {
      temp_c: this.val(e.temp_c),
      humidity_pct: this.val(e.humidity_pct),
      ghi_wm2: this.val(e.ghi_wm2),
      cloud_fraction: this.val(e.cloud_fraction),
      wind_ms: this.val(e.wind_ms)
    };
    this.saving = true;
    this.editError = null;
    const req$ =
      e.mode === 'add'
        ? this.service.add({ ...body, station_id: e.station_id!, ts: e.ts + ':00+05:30' })
        : this.service.update(e.station_id!, e.ts, body);
    req$.subscribe({
      next: () => {
        this.saving = false;
        this.edit = null;
        this.fetchRows();
        this.loadStations();
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
    this.toDelete = row as unknown as WeatherReading;
  }

  deleteConfirmed(): void {
    const t = this.toDelete;
    if (!t) {
      return;
    }
    this.deleting = true;
    this.service.delete(t.station_id, t.ts).subscribe({
      next: () => {
        this.deleting = false;
        this.toDelete = null;
        this.fetchRows();
        this.loadStations();
      },
      error: (err) => {
        this.deleting = false;
        this.deleteError = err?.error?.detail || 'Deleting failed.';
      }
    });
  }
}
