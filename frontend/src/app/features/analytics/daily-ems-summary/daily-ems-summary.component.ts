import { CommonModule } from '@angular/common';
import { AfterViewInit, Component, inject, ElementRef, OnDestroy, OnInit, ViewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute } from '@angular/router';
import { Chart, ChartConfiguration, registerables } from 'chart.js';
import { firstValueFrom, forkJoin } from 'rxjs';

import { EmsDailySummary } from '../../../core/models/ems-analytics.model';
import { EmsController, EmsTelemetry } from '../../../core/models/ems-telemetry.model';
import { EmsAnalyticsService } from '../../../core/services/ems-analytics.service';
import { EmsTelemetryService } from '../../../core/services/ems-telemetry.service';
import { PlantContext, PlantContextService } from '../../../core/services/plant-context.service';
import { ReportExporter, fileSafe, reportDate } from '../../../core/utils/pdf-report';
import { PdfButtonComponent, ReportField, ReportHeaderComponent } from '../../../shared/report/report-header.component';

Chart.register(...registerables);

function toNum(value: unknown): number | null {
  if (value === null || value === undefined || value === '') {
    return null;
  }
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

type MetricIcon = 'charge' | 'discharge' | 'dollar' | 'price' | 'wave' | 'plug' | 'health';

interface MetricCard {
  label: string;
  value: number | null;
  unit: string;
  decimals: number;
  icon: MetricIcon;
}

const MAX_SERIES_DAYS = 90;

@Component({
  selector: 'app-daily-ems-summary',
  standalone: true,
  imports: [CommonModule, FormsModule, ReportHeaderComponent, PdfButtonComponent],
  templateUrl: './daily-ems-summary.component.html',
  styleUrl: './daily-ems-summary.component.scss'
})
export class DailyEmsSummaryComponent implements OnInit, AfterViewInit, OnDestroy {
  @ViewChild('reportRoot') reportRoot?: ElementRef<HTMLElement>;
  /** PDF report state (Download PDF button). */
  readonly report = new ReportExporter();
  /** Plant and battery system of the selection (report header); resolved when a PDF is made. */
  plantContext: PlantContext = { plant: null, system: null };
  private plantContextService = inject(PlantContextService);

  @ViewChild('revenueChart') revenueChartRef!: ElementRef<HTMLCanvasElement>;
  @ViewChild('poiEnergyChart') poiEnergyChartRef!: ElementRef<HTMLCanvasElement>;
  @ViewChild('priceSocChart') priceSocChartRef!: ElementRef<HTMLCanvasElement>;
  @ViewChild('importExportChart') importExportChartRef!: ElementRef<HTMLCanvasElement>;
  @ViewChild('auxChart') auxChartRef!: ElementRef<HTMLCanvasElement>;
  @ViewChild('peakExportChart') peakExportChartRef!: ElementRef<HTMLCanvasElement>;

  controllers: EmsController[] = [];
  selectedEmsId = '';
  selectedDate = '';
  minAvailableDate: string | null = null;
  maxAvailableDate: string | null = null;

  summary: EmsDailySummary | null = null;
  loadingSummary = false;
  loadingCharts = false;
  error: string | null = null;
  viewReady = false;

  private charts: Record<string, Chart> = {};

  constructor(
    private route: ActivatedRoute,
    private telemetryService: EmsTelemetryService,
    private analyticsService: EmsAnalyticsService
  ) {}

  ngOnInit(): void {
    this.telemetryService.lookups().subscribe({
      next: (lookups) => {
        this.controllers = lookups.controllers;
        if (lookups.controllers.length > 0) {
          // ?ems=<ems_id> (e.g. from the Plant 3D View EMS panel) preselects that controller
          const requested = Number(this.route.snapshot.queryParamMap.get('ems'));
          const match = lookups.controllers.find((c) => c.ems_id === requested);
          this.selectedEmsId = String((match ?? lookups.controllers[0]).ems_id);
          this.onControllerChange();
        } else {
          this.loadingSummary = false;
          this.error = 'No EMS controllers found.';
        }
      },
      error: () => {
        this.error = 'Could not load EMS controllers. Is the backend running?';
      }
    });
  }

  ngAfterViewInit(): void {
    this.viewReady = true;
    if (this.summary) {
      this.refreshCharts();
    }
  }

  ngOnDestroy(): void {
    Object.values(this.charts).forEach((chart) => chart.destroy());
  }

  get reportFields(): ReportField[] {
    return [
      { label: 'Plant', value: this.plantContext.plant },
      { label: 'Battery System', value: this.plantContext.system },
      { label: 'EMS Controller', value: this.controllers.find((c) => String(c.ems_id) === this.selectedEmsId)?.ems_code },
      { label: 'Date', value: reportDate(this.selectedDate) }
    ];
  }

  /** Download the report as shown on the page, with the selected plant, system, unit and date at the top. */
  async downloadPdf(): Promise<void> {
    if (!this.reportRoot || !this.summary) {
      return;
    }
    this.plantContext = await firstValueFrom(this.plantContextService.forEms(Number(this.selectedEmsId)));
    const unit = this.controllers.find((c) => String(c.ems_id) === this.selectedEmsId)?.ems_code ?? '';
    await this.report.download(this.reportRoot.nativeElement, {
      fileName: `Daily_EMS_Summary_${fileSafe(this.plantContext.plant, 'Plant')}_${fileSafe(unit, 'Unit')}_${this.selectedDate}.pdf`,
      footer: `Daily EMS Summary · ${this.plantContext.plant ?? ''} · ${unit} · ${this.selectedDate}`
    });
  }

  get metricCards(): MetricCard[] {
    const s = this.summary;
    return [
      { label: 'Peak Grid Import', value: s?.peak_grid_import_kw ?? null, unit: 'kW', decimals: 1, icon: 'charge' },
      { label: 'Peak Grid Export', value: s?.peak_grid_export_kw ?? null, unit: 'kW', decimals: 1, icon: 'discharge' },
      { label: 'Energy Imported (POI)', value: s?.energy_imported_kwh ?? null, unit: 'kWh', decimals: 1, icon: 'charge' },
      { label: 'Energy Exported (POI)', value: s?.energy_exported_kwh ?? null, unit: 'kWh', decimals: 1, icon: 'discharge' },
      { label: 'Net Market Revenue', value: s?.net_market_revenue_usd ?? null, unit: 'USD', decimals: 2, icon: 'dollar' },
      { label: 'Avg Market Price', value: s?.avg_market_price ?? null, unit: '/MWh', decimals: 2, icon: 'price' },
      { label: 'Max Market Price', value: s?.max_market_price ?? null, unit: '/MWh', decimals: 2, icon: 'price' },
      {
        label: 'Avg Realized Price (Export)',
        value: s?.avg_realized_export_price ?? null,
        unit: '/MWh',
        decimals: 2,
        icon: 'price'
      },
      {
        label: 'RMS Setpoint Tracking Error',
        value: s?.rms_tracking_error_kw ?? null,
        unit: 'kW',
        decimals: 3,
        icon: 'wave'
      },
      { label: 'Aux Energy Consumed', value: s?.aux_energy_kwh ?? null, unit: 'kWh', decimals: 1, icon: 'plug' },
      { label: 'Plant Availability', value: s?.availability_pct ?? null, unit: '%', decimals: 1, icon: 'health' }
    ];
  }

  onControllerChange(): void {
    if (!this.selectedEmsId) {
      return;
    }
    this.analyticsService.telemetryDateRange(Number(this.selectedEmsId)).subscribe({
      next: (range) => {
        this.minAvailableDate = range.min_date;
        this.maxAvailableDate = range.max_date;
        this.selectedDate = range.max_date ?? '';
        if (this.selectedDate) {
          this.loadAll();
        } else {
          this.summary = null;
          this.error = 'No EMS telemetry data found for this controller.';
        }
      },
      error: () => {
        this.error = 'Could not load telemetry date range.';
      }
    });
  }

  onDateChange(): void {
    if (this.selectedDate) {
      this.loadAll();
    }
  }

  private loadAll(): void {
    this.loadSummary();
    this.loadCharts();
  }

  private loadSummary(): void {
    this.loadingSummary = true;
    this.error = null;
    this.analyticsService.dailySummary(Number(this.selectedEmsId), this.selectedDate).subscribe({
      next: (summary) => {
        this.summary = summary;
        this.loadingSummary = false;
      },
      error: () => {
        this.summary = null;
        this.loadingSummary = false;
        this.error = 'No EMS telemetry data for this controller on the selected date.';
      }
    });
  }

  private loadCharts(): void {
    this.loadingCharts = true;
    const dayStart = `${this.selectedDate}T00:00:00`;
    const dayEnd = `${this.selectedDate}T23:59:59`;
    const seriesStart = this.clampSeriesStart();
    const auxStart = this.minusDays(this.selectedDate, 6);
    const emsId = Number(this.selectedEmsId);

    forkJoin({
      intraday: this.telemetryService.list({
        emsId,
        start: dayStart,
        end: dayEnd,
        page: 1,
        pageSize: 3000
      }),
      series: this.analyticsService.dailySeries(emsId, seriesStart, this.maxAvailableDate ?? this.selectedDate),
      auxSeries: this.analyticsService.dailySeries(emsId, auxStart, this.selectedDate)
    }).subscribe({
      next: ({ intraday, series, auxSeries }) => {
        const rows = [...intraday.items].sort((a, b) => a.ts.localeCompare(b.ts));
        this.loadingCharts = false;
        this.renderIntradayCharts(rows);
        this.renderSeriesCharts(series);
        this.renderAuxChart(auxSeries);
      },
      error: () => {
        this.loadingCharts = false;
        this.error = 'Could not load chart data.';
      }
    });
  }

  private minusDays(isoDate: string, days: number): string {
    const d = new Date(`${isoDate}T00:00:00`);
    d.setDate(d.getDate() - days);
    return d.toISOString().slice(0, 10);
  }

  private clampSeriesStart(): string {
    if (!this.minAvailableDate) {
      return this.selectedDate;
    }
    const min = new Date(this.minAvailableDate);
    const max = new Date(this.maxAvailableDate ?? this.selectedDate);
    const spanDays = Math.round((max.getTime() - min.getTime()) / 86400000);
    if (spanDays <= MAX_SERIES_DAYS) {
      return this.minAvailableDate;
    }
    const clamped = new Date(max.getTime() - MAX_SERIES_DAYS * 86400000);
    return clamped.toISOString().slice(0, 10);
  }

  private refreshCharts(): void {
    if (this.selectedDate) {
      this.loadCharts();
    }
  }

  private renderIntradayCharts(rows: EmsTelemetry[]): void {
    if (!this.viewReady) {
      return;
    }
    const labels = rows.map((r) => this.formatTime(r.ts));

    this.upsertLineChart(
      'importExport',
      this.importExportChartRef,
      labels,
      [
        { label: 'Import (kWh)', data: rows.map((r) => toNum(r.cum_import_kwh)), color: '#0e8f66' },
        { label: 'Export (kWh)', data: rows.map((r) => toNum(r.cum_export_kwh)), color: '#e5484d' }
      ],
      'Time',
      'Energy (kWh)'
    );
  }

  private renderSeriesCharts(series: EmsDailySummary[]): void {
    if (!this.viewReady) {
      return;
    }
    const labels = series.map((s) => s.date);

    this.upsertBarChart(
      'revenue',
      this.revenueChartRef,
      labels,
      [{ label: 'Net Market Revenue (USD)', data: series.map((s) => toNum(s.net_market_revenue_usd)), color: '#0e8f66' }],
      'Date',
      'Revenue (USD)'
    );

    this.upsertBarChart(
      'poiEnergy',
      this.poiEnergyChartRef,
      labels,
      [
        { label: 'Imported (kWh)', data: series.map((s) => toNum(s.energy_imported_kwh)), color: '#0e8f66' },
        { label: 'Exported (kWh)', data: series.map((s) => toNum(s.energy_exported_kwh)), color: '#e5484d' }
      ],
      'Date',
      'Energy (kWh)'
    );

    this.upsertLineChart(
      'priceSoc',
      this.priceSocChartRef,
      labels,
      [
        { label: 'Avg Market Price ($/MWh)', data: series.map((s) => toNum(s.avg_market_price)), color: '#e08a1e' },
        { label: 'Avg SOC (%)', data: series.map((s) => toNum(s.avg_plant_soc)), color: '#2f6fed' }
      ],
      'Date',
      'Price ($/MWh) / SOC (%)'
    );

    this.upsertLineChart(
      'peakExport',
      this.peakExportChartRef,
      labels,
      [{ label: 'Peak Export (kW)', data: series.map((s) => toNum(s.peak_grid_export_kw)), color: '#e5484d' }],
      'Date',
      'Power (kW)'
    );
  }

  private renderAuxChart(series: EmsDailySummary[]): void {
    if (!this.viewReady) {
      return;
    }
    const labels = series.map((s) => s.date);
    this.upsertBarChart(
      'aux',
      this.auxChartRef,
      labels,
      [{ label: 'Aux Energy (kWh)', data: series.map((s) => toNum(s.aux_energy_kwh)), color: '#8046e5' }],
      'Date',
      'Energy (kWh)'
    );
  }

  private formatTime(iso: string): string {
    const d = new Date(iso);
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }

  private upsertLineChart(
    key: string,
    ref: ElementRef<HTMLCanvasElement>,
    labels: string[],
    datasets: { label: string; data: (number | null)[]; color: string }[],
    xLabel: string,
    yLabel: string
  ): void {
    if (!ref?.nativeElement) {
      return;
    }
    this.charts[key]?.destroy();
    const config: ChartConfiguration<'line'> = {
      type: 'line',
      data: {
        labels,
        datasets: datasets.map((d) => ({
          label: d.label,
          data: d.data,
          borderColor: d.color,
          backgroundColor: d.color,
          pointRadius: 0,
          borderWidth: 2,
          tension: 0.15
        }))
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        scales: {
          x: { ticks: { maxTicksLimit: 8 }, title: { display: true, text: xLabel } },
          y: { title: { display: true, text: yLabel } }
        }
      }
    };
    this.charts[key] = new Chart(ref.nativeElement, config);
  }

  private upsertBarChart(
    key: string,
    ref: ElementRef<HTMLCanvasElement>,
    labels: string[],
    datasets: { label: string; data: (number | null)[]; color: string }[],
    xLabel: string,
    yLabel: string
  ): void {
    if (!ref?.nativeElement) {
      return;
    }
    this.charts[key]?.destroy();
    const config: ChartConfiguration<'bar'> = {
      type: 'bar',
      data: {
        labels,
        datasets: datasets.map((d) => ({ label: d.label, data: d.data, backgroundColor: d.color }))
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: { ticks: { maxTicksLimit: 10 }, title: { display: true, text: xLabel } },
          y: { title: { display: true, text: yLabel } }
        }
      }
    };
    this.charts[key] = new Chart(ref.nativeElement, config);
  }
}
