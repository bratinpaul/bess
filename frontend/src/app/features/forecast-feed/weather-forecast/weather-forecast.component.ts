import { CommonModule, DatePipe } from '@angular/common';
import { Component, ElementRef, OnInit, ViewChild, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { ChartConfiguration } from 'chart.js';
import { map } from 'rxjs';

import {
  BulkWeatherForecastResult,
  ForecastRun,
  WeatherForecastInput,
  WeatherForecastSkill,
  WeatherForecastValue
} from '../../../core/models/weather-forecast.model';
import { WeatherStation } from '../../../core/models/weather.model';
import { WeatherForecastService } from '../../../core/services/weather-forecast.service';
import { ChartCanvasComponent } from '../../telemetry/graphs/chart-canvas.component';
import { GraphEntity, SeriesLoader, SeriesPoint } from '../../telemetry/graphs/chart-spec';
import { TelemetryGraphsComponent } from '../../telemetry/graphs/telemetry-graphs.component';
import { ColumnPickerComponent } from '../../telemetry/table/column-picker.component';
import { TableColumn, TableRow } from '../../telemetry/table/table-column';
import { TelemetryTableComponent } from '../../telemetry/table/telemetry-table.component';
import {
  DEFAULT_FORECAST_COLUMN_KEYS,
  FORECAST_CHARTS,
  FORECAST_TABLE_COLUMNS,
  FORECAST_TIMELINES
} from './weather-forecast-specs';

const PAGE_SIZE_OPTIONS = [25, 50, 100];
const PLANT_OFFSET = '+05:30';

interface EditState {
  mode: 'add' | 'edit';
  station_id: number | null;
  issued_at: string; // datetime-local (plant time) in add mode; the stored ISO time in edit mode
  valid_at: string;
  temp_c: number | null;
  ghi_wm2: number | null;
}

/** Forecast feed -> Weather Forecast: forecast runs per weather station (temperature, GHI for each hour ahead),
 *  upload, add / edit / delete values, tabular view, forecast-vs-measured graphs and skill by lead time. */
@Component({
  selector: 'app-weather-forecast',
  standalone: true,
  imports: [CommonModule, FormsModule, TelemetryGraphsComponent, ColumnPickerComponent, TelemetryTableComponent, ChartCanvasComponent],
  providers: [DatePipe],
  templateUrl: './weather-forecast.component.html',
  styleUrl: './weather-forecast.component.scss'
})
export class WeatherForecastComponent implements OnInit {
  private route = inject(ActivatedRoute);
  private router = inject(Router);
  private datePipe = inject(DatePipe);
  @ViewChild('fileInput') fileInput?: ElementRef<HTMLInputElement>;

  stations: WeatherStation[] = [];
  runs: ForecastRun[] = [];

  // upload
  showUpload = false;
  selectedFile: File | null = null;
  uploadCode = '';
  uploading = false;
  uploadResult: BulkWeatherForecastResult | null = null;
  uploadError: string | null = null;
  showAllUploadErrors = false;

  // table
  readonly allColumns = FORECAST_TABLE_COLUMNS;
  readonly defaultColumnKeys = DEFAULT_FORECAST_COLUMN_KEYS;
  visibleColumns: TableColumn[] = FORECAST_TABLE_COLUMNS;
  rows: WeatherForecastValue[] = [];
  tableRows: TableRow[] = [];
  total = 0;
  loading = true;
  error: string | null = null;
  filterStationId = '';
  filterRun = '';
  filterStart = '';
  filterEnd = '';
  pageSizeOptions = PAGE_SIZE_OPTIONS;
  pageSize = PAGE_SIZE_OPTIONS[0];
  currentPage = 1;

  activeTab: 'tabular' | 'graphical' = 'tabular';

  // graphs: entity = "<station>" (latest run for each hour) or "<station>|<issued_at>" (one run)
  readonly graphCharts = FORECAST_CHARTS;
  readonly graphTimelines = FORECAST_TIMELINES;
  graphEntities: GraphEntity[] = [];
  readonly loadGraphSeries: SeriesLoader = (id, start, end) => {
    const [station, run] = id.split('|');
    return this.service.series(Number(station), run || null, start, end).pipe(
      map((s) => ({
        entityName: run ? `${s.station_code} · run ${this.fmt(run)}` : `${s.station_code} · latest run per hour`,
        start: s.start,
        end: s.end,
        bucketSeconds: s.bucket_seconds,
        rawIntervalSeconds: s.raw_interval_seconds,
        points: s.points as SeriesPoint[],
        timelines: s.timelines,
        refs: { tempMae: s.refs['temp_mae'], ghiMae: s.refs['ghi_mae'] }
      }))
    );
  };

  // skill by lead time
  skillStationId = '';
  skill: WeatherForecastSkill | null = null;
  skillLoading = false;
  skillError: string | null = null;
  tempSkillConfig: ChartConfiguration | null = null;
  ghiSkillConfig: ChartConfiguration | null = null;

  // add / edit / delete
  edit: EditState | null = null;
  saving = false;
  editError: string | null = null;
  toDelete: WeatherForecastValue | null = null;
  deleting = false;
  deleteError: string | null = null;

  constructor(private service: WeatherForecastService) {}

  ngOnInit(): void {
    if (this.route.snapshot.queryParamMap.get('view') === 'graphical') {
      this.activeTab = 'graphical';
    }
    this.loadLookups();
    this.fetchRows();
  }

  fmt(iso: string | null | undefined): string {
    return iso ? this.datePipe.transform(iso, 'yyyy-MM-dd HH:mm', PLANT_OFFSET) ?? iso : '—';
  }

  private loadLookups(): void {
    this.service.lookups().subscribe({
      next: (lk) => {
        this.stations = lk.stations;
        this.runs = lk.runs;
        const entities: GraphEntity[] = [];
        for (const s of lk.stations) {
          entities.push({ id: String(s.station_id), name: `${s.station_code} · latest run per hour` });
          for (const r of lk.runs.filter((x) => x.station_id === s.station_id)) {
            entities.push({ id: `${s.station_id}|${r.issued_at}`, name: `${s.station_code} · run ${this.fmt(r.issued_at)} (${r.points} h)` });
          }
        }
        this.graphEntities = entities;
        if (!this.skillStationId && lk.stations.length) {
          this.skillStationId = String(lk.stations[0].station_id);
          if (this.activeTab === 'graphical') {
            this.loadSkill();
          }
        }
      },
      error: () => (this.error = 'Could not load the weather stations. Is the backend running?')
    });
  }

  get filterRuns(): ForecastRun[] {
    return this.filterStationId ? this.runs.filter((r) => String(r.station_id) === this.filterStationId) : this.runs;
  }

  setTab(tab: 'tabular' | 'graphical'): void {
    this.activeTab = tab;
    if (tab === 'graphical' && !this.skill && this.skillStationId) {
      this.loadSkill();
    }
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
        issuedAt: this.filterRun || undefined,
        start: this.filterStart || undefined,
        end: this.filterEnd || undefined,
        page: this.currentPage,
        pageSize: this.pageSize
      })
      .subscribe({
        next: (page) => {
          this.rows = page.items;
          this.tableRows = page.items.map((r) => ({ ...r, issued_label: this.fmt(r.issued_at) }) as unknown as TableRow);
          this.total = page.total;
          this.loading = false;
        },
        error: () => {
          this.error = 'Could not load weather forecasts. Is the backend running?';
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
    this.filterRun = '';
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

  // ---------------------------------------------------------------- skill

  loadSkill(): void {
    if (!this.skillStationId) {
      return;
    }
    this.skillLoading = true;
    this.skillError = null;
    this.service.skill(Number(this.skillStationId)).subscribe({
      next: (sk) => {
        this.skill = sk;
        this.skillLoading = false;
        this.tempSkillConfig = this.skillChart(sk, 'temp_mae', 'temp_bias', '°C', '#d62828');
        this.ghiSkillConfig = this.skillChart(sk, 'ghi_mae', 'ghi_bias', 'W/m²', '#e8830c');
      },
      error: () => {
        this.skillError = 'Could not compute forecast skill.';
        this.skillLoading = false;
      }
    });
  }

  private skillChart(sk: WeatherForecastSkill, maeKey: 'temp_mae' | 'ghi_mae', biasKey: 'temp_bias' | 'ghi_bias',
                     unit: string, color: string): ChartConfiguration {
    const labels = sk.by_lead.map((l) => `+${l.lead_h}h`);
    return {
      type: 'bar',
      data: {
        labels,
        datasets: [
          {
            type: 'bar',
            label: `MAE (${unit})`,
            data: sk.by_lead.map((l) => l[maeKey]),
            backgroundColor: color,
            borderRadius: { topLeft: 4, topRight: 4 },
            borderSkipped: 'bottom',
            maxBarThickness: 18,
            order: 2
          },
          {
            type: 'line',
            label: `Bias (${unit}, + = forecast too high)`,
            data: sk.by_lead.map((l) => l[biasKey]),
            borderColor: '#2f6fed',
            backgroundColor: '#2f6fed',
            borderWidth: 2,
            pointRadius: 3,
            pointHoverRadius: 5,
            tension: 0.25,
            order: 1
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { position: 'top', align: 'end', labels: { boxWidth: 12, boxHeight: 12, font: { size: 11 } } },
          tooltip: {
            callbacks: {
              title: (items) => `Lead ${items[0]?.label} · ${sk.by_lead[items[0]?.dataIndex ?? 0]?.n ?? 0} forecasts`
            }
          }
        },
        scales: {
          x: { grid: { display: false }, ticks: { maxRotation: 0, autoSkip: true, autoSkipPadding: 8, font: { size: 10 } } },
          y: { title: { display: true, text: unit }, grid: { color: '#eceef1' }, ticks: { font: { size: 10 } } }
        }
      }
    } as ChartConfiguration;
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
        this.afterChange();
      },
      error: (err) => {
        this.uploadError = err?.error?.detail || 'Upload failed. Is the backend running?';
        this.uploading = false;
      }
    });
  }

  private afterChange(): void {
    this.fetchRows();
    this.loadLookups();
    this.skill = null;
    if (this.activeTab === 'graphical') {
      this.loadSkill();
    }
  }

  // ---------------------------------------------------------------- add / edit / delete

  openAdd(): void {
    const plantNow = new Date(Date.now() + 330 * 60e3);
    plantNow.setUTCMinutes(0, 0, 0);
    const issued = plantNow.toISOString().slice(0, 16);
    const valid = new Date(plantNow.getTime() + 3600e3).toISOString().slice(0, 16);
    this.editError = null;
    this.edit = {
      mode: 'add',
      station_id: this.filterStationId ? Number(this.filterStationId) : this.stations[0]?.station_id ?? null,
      issued_at: issued,
      valid_at: valid,
      temp_c: null,
      ghi_wm2: null
    };
  }

  openEdit(row: TableRow): void {
    const r = row as unknown as WeatherForecastValue;
    const num = (v: unknown) => (v === null || v === undefined || v === '' ? null : Number(v));
    this.editError = null;
    this.edit = {
      mode: 'edit',
      station_id: r.station_id,
      issued_at: r.issued_at,
      valid_at: r.valid_at,
      temp_c: num(r.temp_c),
      ghi_wm2: num(r.ghi_wm2)
    };
  }

  private val(v: number | null | undefined): number | null {
    return v === null || v === undefined || (v as unknown) === '' ? null : Number(v);
  }

  get editLeadHours(): number | null {
    const e = this.edit;
    if (!e || !e.issued_at || !e.valid_at) {
      return null;
    }
    const toMs = (s: string) => Date.parse(e.mode === 'add' ? s + ':00' + PLANT_OFFSET : s);
    return Math.round(((toMs(e.valid_at) - toMs(e.issued_at)) / 3600e3) * 100) / 100;
  }

  get editProblem(): string | null {
    const e = this.edit;
    if (!e) {
      return null;
    }
    if (!e.station_id) {
      return 'Choose a weather station';
    }
    if (!e.issued_at || !e.valid_at) {
      return 'Enter the issue time and the valid hour';
    }
    const lead = this.editLeadHours;
    if (lead !== null && lead <= 0) {
      return 'The valid hour must be after the issue time';
    }
    if (lead !== null && lead > 16 * 24) {
      return 'The valid hour is more than 16 days after the issue time';
    }
    const t = this.val(e.temp_c);
    const g = this.val(e.ghi_wm2);
    if (t === null && g === null) {
      return 'Enter the forecast temperature or GHI';
    }
    if (t !== null && (t < -60 || t > 65)) {
      return 'Temperature must be between -60 and 65 °C';
    }
    if (g !== null && (g < 0 || g > 1500)) {
      return 'GHI must be between 0 and 1500 W/m²';
    }
    return null;
  }

  save(): void {
    const e = this.edit;
    if (!e || this.editProblem) {
      return;
    }
    const body: WeatherForecastInput = { temp_c: this.val(e.temp_c), ghi_wm2: this.val(e.ghi_wm2) };
    this.saving = true;
    this.editError = null;
    const req$ =
      e.mode === 'add'
        ? this.service.add({
            ...body,
            station_id: e.station_id!,
            issued_at: e.issued_at + ':00' + PLANT_OFFSET,
            valid_at: e.valid_at + ':00' + PLANT_OFFSET
          })
        : this.service.update(e.station_id!, e.issued_at, e.valid_at, body);
    req$.subscribe({
      next: () => {
        this.saving = false;
        this.edit = null;
        this.afterChange();
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
    this.toDelete = row as unknown as WeatherForecastValue;
  }

  deleteConfirmed(): void {
    const t = this.toDelete;
    if (!t) {
      return;
    }
    this.deleting = true;
    this.service.delete(t.station_id, t.issued_at, t.valid_at).subscribe({
      next: () => {
        this.deleting = false;
        this.toDelete = null;
        this.afterChange();
      },
      error: (err) => {
        this.deleting = false;
        this.deleteError = err?.error?.detail || 'Deleting failed.';
      }
    });
  }
}
