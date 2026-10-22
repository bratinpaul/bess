import { CommonModule } from '@angular/common';
import { AfterViewInit, Component, ElementRef, OnDestroy, OnInit, ViewChild, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute } from '@angular/router';
import { Chart, ChartConfiguration, registerables } from 'chart.js';
import { catchError, firstValueFrom, forkJoin, of } from 'rxjs';

import { ModuleSummaryByModule, ModuleSummaryDaily, ModuleTelemetrySummary } from '../../../core/models/module-telemetry.model';
import { BatteryContainer } from '../../../core/models/battery-container.model';
import { BatteryPack } from '../../../core/models/battery-pack.model';
import { BatterySystem } from '../../../core/models/battery-system.model';
import { BatteryContainerService } from '../../../core/services/battery-container.service';
import { BatteryPackService } from '../../../core/services/battery-pack.service';
import { BatterySystemService } from '../../../core/services/battery-system.service';
import { ModuleTelemetryService } from '../../../core/services/module-telemetry.service';
import { PlantContext, PlantContextService } from '../../../core/services/plant-context.service';
import { ReportExporter, fileSafe, reportDate } from '../../../core/utils/pdf-report';
import { PdfButtonComponent, ReportField, ReportHeaderComponent } from '../../../shared/report/report-header.component';
import {
  COMPARISON_METRICS,
  ColumnStats,
  ComparisonMetric,
  MetricKey,
  cellShade,
  columnStats
} from './module-comparison';

Chart.register(...registerables);

type MetricIcon = 'modules' | 'samples' | 'voltage' | 'imbalance' | 'temp' | 'duty' | 'clock' | 'warning';

interface MetricCard {
  label: string;
  /** Numeric value (formatted with `decimals`), or preformatted text such as a range. */
  value: number | string | null;
  unit: string;
  decimals: number;
  icon: MetricIcon;
}

const IMBALANCE_COLOR = '#e8830c';
const BALANCING_COLOR = '#12a37f';
const TEMP_COLOR = '#e5484d';
const COMPARE_COLOR = '#9fb6e8';
const COMPARE_HIGHLIGHT = '#2f6fed';
const PACK_LINE_COLOR = '#5b6472';

type SortKey = MetricKey | 'module';

@Component({
  selector: 'app-daily-module-summary',
  standalone: true,
  imports: [CommonModule, FormsModule, ReportHeaderComponent, PdfButtonComponent],
  templateUrl: './daily-module-summary.component.html',
  styleUrl: './daily-module-summary.component.scss'
})
export class DailyModuleSummaryComponent implements OnInit, AfterViewInit, OnDestroy {
  @ViewChild('reportRoot') reportRoot?: ElementRef<HTMLElement>;
  /** PDF report state (Download PDF button). */
  readonly report = new ReportExporter();
  /** Plant and battery system of the selection (report header); resolved when a PDF is made. */
  plantContext: PlantContext = { plant: null, system: null };
  private plantContextService = inject(PlantContextService);

  private telemetryService = inject(ModuleTelemetryService);
  private systemService = inject(BatterySystemService);
  private containerService = inject(BatteryContainerService);
  private packService = inject(BatteryPackService);
  private route = inject(ActivatedRoute);

  @ViewChild('imbalanceChart') imbalanceChartRef?: ElementRef<HTMLCanvasElement>;
  @ViewChild('balancingChart') balancingChartRef?: ElementRef<HTMLCanvasElement>;
  @ViewChild('dailyChart') dailyChartRef?: ElementRef<HTMLCanvasElement>;
  @ViewChild('compareChart') compareChartRef?: ElementRef<HTMLCanvasElement>;

  // scope: all modules, or one battery system and/or pack (?system= / ?pack=, e.g. from the Plant 3D View)
  systems: BatterySystem[] = [];
  packs: BatteryPack[] = [];
  selectedSystemId: number | null = null;
  selectedPackId: number | null = null;
  /** ?module=<id>: the module to highlight in the comparison table (e.g. from the module pages). */
  highlightModuleId: number | null = null;
  private containers: BatteryContainer[] = [];
  private allPacks: BatteryPack[] = [];

  minDate: string | null = null;
  maxDate: string | null = null;
  /** The one day the summary covers (default: today; ?date=YYYY-MM-DD). */
  selectedDate = localToday();
  readonly today = localToday();
  /** The daily trend chart: the 7 days up to and including the selected date (a missing day is a gap). */
  weekDaily: ModuleSummaryDaily[] = [];

  summary: ModuleTelemetrySummary | null = null;
  metricCards: MetricCard[] = this.buildCards(null);
  loading = true;
  error: string | null = null;

  // Module comparison (ByModule)
  readonly comparisonMetrics = COMPARISON_METRICS;
  readonly chartMetrics = COMPARISON_METRICS.filter((m) => m.chartable);
  compareMetricKey: MetricKey = 'max_imbalance_mv';
  sortKey: SortKey = 'module';
  sortDesc = false;
  sortedModules: ModuleSummaryByModule[] = [];
  stats: Record<string, ColumnStats | null> = {};

  private charts: Record<string, Chart> = {};
  private viewReady = false;

  ngOnInit(): void {
    const params = this.route.snapshot.queryParamMap;
    const system = Number(params.get('system'));
    const pack = Number(params.get('pack'));
    this.selectedSystemId = system > 0 ? system : null;
    this.selectedPackId = pack > 0 ? pack : null;
    const date = params.get('date');
    if (date && /^\d{4}-\d{2}-\d{2}$/.test(date)) {
      this.selectedDate = date;
    }
    const module = Number(params.get('module'));
    this.highlightModuleId = module > 0 ? module : null;

    forkJoin({
      systems: this.systemService.list(),
      containers: this.containerService.list(),
      packs: this.packService.list()
    }).subscribe({
      next: ({ systems, containers, packs }) => {
        this.systems = systems;
        this.containers = containers;
        this.allPacks = packs;
        this.refreshPackOptions();
        this.loadDateRange();
      },
      // the dropdowns are optional context; the summary still works without them
      error: () => this.loadDateRange()
    });
  }

  onSystemChange(): void {
    this.refreshPackOptions();
    this.loadDateRange();
  }

  onPackChange(): void {
    this.loadDateRange();
  }

  /** The battery system of the selection: the chosen system, or the system of the chosen pack. */
  private get reportSystemId(): number | null {
    if (this.selectedSystemId !== null) {
      return this.selectedSystemId;
    }
    const pack = this.allPacks.find((p) => p.pack_id === this.selectedPackId);
    return this.containers.find((c) => c.container_id === pack?.container_id)?.battery_system_id ?? null;
  }

  get reportFields(): ReportField[] {
    const pack = this.allPacks.find((p) => p.pack_id === this.selectedPackId);
    const all = this.reportSystemId === null;
    return [
      { label: 'Plant', value: all ? 'All plants' : this.plantContext.plant },
      { label: 'Battery System', value: all ? 'All systems' : this.plantContext.system },
      { label: 'Pack', value: pack ? pack.pack_number || `Pack ${pack.pack_id}` : 'All packs' },
      { label: 'Date', value: reportDate(this.summary?.start_date ?? this.selectedDate) }
    ];
  }

  /** Download the report as shown on the page, with the selected plant, system, pack and date at the top. */
  async downloadPdf(): Promise<void> {
    if (!this.reportRoot || !this.summary) {
      return;
    }
    this.plantContext = await firstValueFrom(this.plantContextService.forSystem(this.reportSystemId));
    const all = this.reportSystemId === null;
    const plant = all ? 'All_plants' : fileSafe(this.plantContext.plant, 'Plant');
    const period = this.summary.start_date;
    await this.report.download(this.reportRoot.nativeElement, {
      fileName: `Daily_Module_Summary_${plant}_${fileSafe(this.scopeLabel, 'Modules')}_${period}.pdf`,
      footer: `Daily Module Summary · ${all ? 'All plants' : this.plantContext.plant ?? ''} · ${this.scopeLabel} · ${this.periodLabel}`
    });
  }

  get scopeLabel(): string {
    const pack = this.allPacks.find((p) => p.pack_id === this.selectedPackId);
    if (pack) {
      return pack.pack_number || `Pack ${pack.pack_id}`;
    }
    const system = this.systems.find((s) => s.battery_system_id === this.selectedSystemId);
    return system ? system.system_name : 'All modules';
  }

  /** Packs offered in the Pack dropdown: those of the selected battery system, or all. */
  private refreshPackOptions(): void {
    const containerIds = new Set(
      this.containers
        .filter((c) => this.selectedSystemId === null || c.battery_system_id === this.selectedSystemId)
        .map((c) => c.container_id)
    );
    this.packs = this.allPacks.filter((p) => this.selectedSystemId === null || containerIds.has(p.container_id));
    if (this.selectedPackId !== null && !this.packs.some((p) => p.pack_id === this.selectedPackId)) {
      this.selectedPackId = null;
    }
  }

  private loadDateRange(): void {
    this.loading = true;
    this.error = null;
    this.telemetryService.dateRange(this.selectedPackId, this.selectedSystemId).subscribe({
      next: (range) => {
        this.minDate = range.first_date;
        this.maxDate = range.last_date;
        if (!range.first_date || !range.last_date) {
          this.summary = null;
          this.prepareComparison();
          this.metricCards = this.buildCards(null);
          this.loading = false;
          this.error =
            this.selectedPackId || this.selectedSystemId
              ? `No module telemetry for ${this.scopeLabel} yet.`
              : 'No module telemetry has been loaded yet. Upload it on Telemetry → Module.';
          this.renderCharts();
          return;
        }
        this.load();
      },
      error: () => {
        this.loading = false;
        this.error = 'Could not load module telemetry. Is the backend running?';
      }
    });
  }

  ngAfterViewInit(): void {
    this.viewReady = true;
    this.renderCharts();
  }

  ngOnDestroy(): void {
    Object.values(this.charts).forEach((c) => c.destroy());
  }

  get periodLabel(): string {
    return this.summary ? this.summary.start_date : '';
  }

  onDateChange(): void {
    if (this.selectedDate) {
      this.load();
    }
  }

  /** Jump to the newest day that has module data. */
  latestDate(): void {
    if (this.maxDate) {
      this.selectedDate = this.maxDate;
      this.load();
    }
  }

  private load(): void {
    // a day without module data (e.g. today before it is loaded): say so instead of an empty summary
    if (this.minDate && this.maxDate && (this.selectedDate < this.minDate || this.selectedDate > this.maxDate)) {
      this.summary = null;
      this.prepareComparison();
      this.metricCards = this.buildCards(null);
      this.loading = false;
      this.error = `No module telemetry for ${this.scopeLabel} on ${this.selectedDate}. Data is available from ` +
        `${this.minDate} to ${this.maxDate} — use "Latest data" or pick another date.`;
      this.weekDaily = [];
      this.renderCharts();
      return;
    }
    this.loading = true;
    this.error = null;
    const weekStart = addDays(this.selectedDate, -6);
    forkJoin({
      summary: this.telemetryService.summary(this.selectedDate, this.selectedDate, this.selectedPackId, this.selectedSystemId),
      // the trend chart only: a week that has no data at all must not fail the day's summary
      week: this.telemetryService
        .summary(weekStart, this.selectedDate, this.selectedPackId, this.selectedSystemId)
        .pipe(catchError(() => of(null)))
    }).subscribe({
      next: ({ summary, week }) => {
        this.weekDaily = lastSevenDays(this.selectedDate, week?.daily ?? []);
        this.summary = summary;
        this.prepareComparison();
        this.metricCards = this.buildCards(summary);
        this.loading = false;
        this.renderCharts();
      },
      error: (err) => {
        this.summary = null;
        this.weekDaily = [];
        this.prepareComparison();
        this.metricCards = this.buildCards(null);
        this.loading = false;
        this.error = err?.error?.detail || 'Could not load the module summary.';
        this.renderCharts();
      }
    });
  }

  private buildCards(s: ModuleTelemetrySummary | null): MetricCard[] {
    const k = s?.kpis;
    const range =
      k?.cell_v_min != null && k?.cell_v_max != null ? `${k.cell_v_min.toFixed(3)}–${k.cell_v_max.toFixed(3)}` : null;
    const worst =
      k?.highest_imbalance_module && k.highest_imbalance_mv != null
        ? `${k.highest_imbalance_module} (${k.highest_imbalance_mv.toFixed(1)} mV)`
        : null;
    return [
      { label: 'Modules', value: k?.modules ?? null, unit: '', decimals: 0, icon: 'modules' },
      { label: 'Samples / Module', value: k?.samples_per_module ?? null, unit: '', decimals: 0, icon: 'samples' },
      { label: 'Cell Voltage Range', value: range, unit: 'V', decimals: 3, icon: 'voltage' },
      { label: 'Mean Imbalance', value: k?.mean_imbalance_mv ?? null, unit: 'mV', decimals: 1, icon: 'imbalance' },
      { label: 'Max Imbalance', value: k?.max_imbalance_mv ?? null, unit: 'mV', decimals: 1, icon: 'imbalance' },
      { label: 'Max Module Temp', value: k?.max_temp_c ?? null, unit: '°C', decimals: 1, icon: 'temp' },
      { label: 'Balancing Duty', value: k?.balancing_duty_pct ?? null, unit: '% of samples', decimals: 1, icon: 'duty' },
      { label: 'Balancing Module-Hours', value: k?.balancing_module_hours ?? null, unit: 'h', decimals: 1, icon: 'clock' },
      { label: 'Highest-Imbalance Module', value: worst, unit: '', decimals: 0, icon: 'warning' }
    ];
  }

  get compareMetric(): ComparisonMetric {
    return this.chartMetrics.find((m) => m.key === this.compareMetricKey) ?? this.chartMetrics[0];
  }

  sortBy(key: SortKey): void {
    if (this.sortKey === key) {
      this.sortDesc = !this.sortDesc;
    } else {
      this.sortKey = key;
      // metrics start with the worst (highest) value on top; modules in number order
      this.sortDesc = key !== 'module';
    }
    this.applySort();
  }

  onCompareMetricChange(): void {
    this.renderCompareChart();
  }

  shade(row: ModuleSummaryByModule, metric: ComparisonMetric): string | null {
    return cellShade(row[metric.key], metric, this.stats[metric.key]);
  }

  /** True for the module with the worst (highest) value in a worse-high column. */
  isWorst(row: ModuleSummaryByModule, metric: ComparisonMetric): boolean {
    const st = this.stats[metric.key];
    return metric.tone === 'worse-high' && !!st && st.max > st.min && row[metric.key] === st.max;
  }

  private prepareComparison(): void {
    const rows = this.summary?.by_module ?? [];
    this.stats = columnStats(rows);
    this.applySort();
  }

  private applySort(): void {
    // by_module arrives in module-number order, which is the "module" sort
    const rows = [...(this.summary?.by_module ?? [])];
    if (this.sortKey !== 'module') {
      const key = this.sortKey;
      rows.sort((a, b) => (a[key] ?? -Infinity) - (b[key] ?? -Infinity));
    }
    if (this.sortDesc) {
      rows.reverse();
    }
    this.sortedModules = rows;
  }

  isText(card: MetricCard): boolean {
    return typeof card.value === 'string';
  }

  private renderCharts(): void {
    if (!this.viewReady) {
      return;
    }
    this.renderCompareChart();
    const byModule = this.summary?.by_module ?? [];
    const daily = this.weekDaily;
    const labels = byModule.map((m) => m.label);

    this.upsert('imbalance', this.imbalanceChartRef, {
      type: 'bar',
      data: {
        labels,
        datasets: [
          {
            label: 'Max imbalance (mV)',
            data: byModule.map((m) => m.max_imbalance_mv),
            backgroundColor: IMBALANCE_COLOR,
            borderRadius: 3
          }
        ]
      },
      options: this.barOptions('mV', (i) => byModule[i]?.serial_number ?? '')
    });

    this.upsert('balancing', this.balancingChartRef, {
      type: 'bar',
      data: {
        labels,
        datasets: [
          {
            label: 'Balancing hours',
            data: byModule.map((m) => m.balancing_hours),
            backgroundColor: BALANCING_COLOR,
            borderRadius: 3
          }
        ]
      },
      options: this.barOptions('h', (i) => byModule[i]?.serial_number ?? '')
    });

    this.upsert('daily', this.dailyChartRef, {
      type: 'line',
      data: {
        labels: daily.map((d) => d.day.slice(5)),
        datasets: [
          {
            label: 'Max imbalance (mV)',
            data: daily.map((d) => d.max_imbalance_mv),
            borderColor: IMBALANCE_COLOR,
            backgroundColor: IMBALANCE_COLOR,
            yAxisID: 'y',
            tension: 0.2,
            pointRadius: daily.length > 40 ? 0 : 3
          },
          {
            label: 'Max module temp (°C)',
            data: daily.map((d) => d.max_temp_c),
            borderColor: TEMP_COLOR,
            backgroundColor: TEMP_COLOR,
            yAxisID: 'y2',
            tension: 0.2,
            pointRadius: daily.length > 40 ? 0 : 3
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: { legend: { position: 'bottom' } },
        scales: {
          x: { title: { display: true, text: 'Date' } },
          y: { position: 'left', title: { display: true, text: 'Max imbalance (mV)' }, beginAtZero: true },
          y2: {
            position: 'right',
            title: { display: true, text: 'Max module temp (°C)' },
            grid: { drawOnChartArea: false }
          }
        }
      }
    });
  }

  private renderCompareChart(): void {
    if (!this.viewReady) {
      return;
    }
    const rows = this.summary?.by_module ?? [];
    const metric = this.compareMetric;
    const st = this.stats[metric.key];
    const vals = rows.map((r) => r[metric.key]);
    // highlight the extreme module: highest for worse-high metrics, both ends for voltage spreads
    const colors = vals.map((v) =>
      st && v !== null && (v === st.max || (metric.tone === 'spread' && v === st.min)) ? COMPARE_HIGHLIGHT : COMPARE_COLOR
    );
    const unit = metric.unit ? ` (${metric.unit})` : '';
    this.upsert('compare', this.compareChartRef, {
      type: 'bar',
      data: {
        labels: rows.map((r) => r.label),
        datasets: [
          { label: metric.label + unit, data: vals, backgroundColor: colors, borderRadius: 3, order: 2 },
          {
            type: 'line',
            label: 'Pack average',
            data: rows.map(() => st?.mean ?? null),
            borderColor: PACK_LINE_COLOR,
            borderDash: [6, 4],
            borderWidth: 1.5,
            pointRadius: 0,
            order: 1
          } as unknown as ChartConfiguration<'bar'>['data']['datasets'][number]
        ]
      },
      options: {
        ...this.barOptions(metric.unit, (i) => rows[i]?.serial_number ?? ''),
        plugins: {
          legend: { display: true, position: 'bottom' },
          tooltip: {
            callbacks: {
              afterTitle: (items) => (items.length ? rows[items[0].dataIndex]?.serial_number ?? '' : ''),
              label: (item) => `${item.dataset.label}: ${Number(item.raw).toFixed(metric.decimals)}`
            }
          }
        },
        scales: {
          x: { title: { display: true, text: 'Module' }, grid: { display: false }, ticks: { autoSkip: false } },
          // voltages sit in a narrow band, so let the axis zoom in instead of starting at zero
          y: { title: { display: true, text: metric.unit }, beginAtZero: metric.tone !== 'spread' }
        }
      }
    });
  }

  private barOptions(unit: string, fullName: (index: number) => string): ChartConfiguration<'bar'>['options'] {
    return {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            // bars are labelled MOD-NN; the tooltip shows the full serial number too
            afterTitle: (items) => (items.length ? fullName(items[0].dataIndex) : '')
          }
        }
      },
      scales: {
        // label every module; Chart.js rotates them when space is tight
        x: { title: { display: true, text: 'Module' }, grid: { display: false }, ticks: { autoSkip: false } },
        y: { title: { display: true, text: unit }, beginAtZero: true }
      }
    };
  }

  private upsert(
    key: string,
    ref: ElementRef<HTMLCanvasElement> | undefined,
    config: ChartConfiguration<'bar'> | ChartConfiguration<'line'>
  ): void {
    if (!ref?.nativeElement) {
      return;
    }
    this.charts[key]?.destroy();
    this.charts[key] = new Chart(ref.nativeElement, config as ChartConfiguration);
  }
}

/** Today in the browser's local time zone as YYYY-MM-DD. */
function localToday(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

/** YYYY-MM-DD plus n days. */
function addDays(iso: string, n: number): string {
  const [y, m, d] = iso.split('-').map(Number);
  const date = new Date(y, m - 1, d + n);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}

/** The 7 days up to and including `end`, from the summary's daily rows; a day without data has empty values. */
function lastSevenDays(end: string, rows: ModuleSummaryDaily[]): ModuleSummaryDaily[] {
  const byDay = new Map(rows.map((r) => [r.day.slice(0, 10), r]));
  return Array.from({ length: 7 }, (_, i) => {
    const day = addDays(end, i - 6);
    return byDay.get(day) ?? { day, max_imbalance_mv: null, avg_imbalance_mv: null, max_temp_c: null, balancing_module_hours: 0, samples: 0 };
  });
}
