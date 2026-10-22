import { CommonModule } from '@angular/common';
import { AfterViewInit, Component, inject, ElementRef, OnDestroy, OnInit, ViewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute } from '@angular/router';
import { Chart, ChartConfiguration, registerables } from 'chart.js';
import { firstValueFrom, forkJoin } from 'rxjs';

import { HvacDailySummary } from '../../../core/models/hvac-analytics.model';
import { HvacUnit } from '../../../core/models/hvac-telemetry.model';
import { HvacAnalyticsService } from '../../../core/services/hvac-analytics.service';
import { HvacTelemetryService } from '../../../core/services/hvac-telemetry.service';
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

type MetricIcon = 'plug' | 'power' | 'heat' | 'cop' | 'temp' | 'humidity' | 'clock' | 'duty' | 'snow';

interface MetricCard {
  label: string;
  value: number | null;
  unit: string;
  decimals: number;
  icon: MetricIcon;
}

const MAX_SERIES_DAYS = 90;

@Component({
  selector: 'app-daily-hvac-summary',
  standalone: true,
  imports: [CommonModule, FormsModule, ReportHeaderComponent, PdfButtonComponent],
  templateUrl: './daily-hvac-summary.component.html',
  styleUrl: './daily-hvac-summary.component.scss'
})
export class DailyHvacSummaryComponent implements OnInit, AfterViewInit, OnDestroy {
  @ViewChild('reportRoot') reportRoot?: ElementRef<HTMLElement>;
  /** PDF report state (Download PDF button). */
  readonly report = new ReportExporter();
  /** Plant and battery system of the selection (report header); resolved when a PDF is made. */
  plantContext: PlantContext = { plant: null, system: null };
  private plantContextService = inject(PlantContextService);

  @ViewChild('energyChart') energyChartRef!: ElementRef<HTMLCanvasElement>;
  @ViewChild('tempChart') tempChartRef!: ElementRef<HTMLCanvasElement>;
  @ViewChild('copChart') copChartRef!: ElementRef<HTMLCanvasElement>;

  units: HvacUnit[] = [];
  selectedHvacId = '';
  selectedDate = '';
  minAvailableDate: string | null = null;
  maxAvailableDate: string | null = null;

  summary: HvacDailySummary | null = null;
  loadingSummary = false;
  loadingCharts = false;
  error: string | null = null;
  viewReady = false;

  private charts: Record<string, Chart> = {};

  constructor(
    private route: ActivatedRoute,
    private telemetryService: HvacTelemetryService,
    private analyticsService: HvacAnalyticsService
  ) {}

  ngOnInit(): void {
    this.telemetryService.lookups().subscribe({
      next: (lookups) => {
        this.units = lookups.units;
        if (lookups.units.length > 0) {
          // ?hvac=<hvac_id> (e.g. from the Plant 3D View HVAC panel) preselects that unit
          const requested = Number(this.route.snapshot.queryParamMap.get('hvac'));
          const match = lookups.units.find((u) => u.hvac_id === requested);
          this.selectedHvacId = String((match ?? lookups.units[0]).hvac_id);
          this.onUnitChange();
        } else {
          this.loadingSummary = false;
          this.error = 'No HVAC units found.';
        }
      },
      error: () => {
        this.error = 'Could not load HVAC units. Is the backend running?';
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
      { label: 'HVAC Unit', value: this.units.find((u) => String(u.hvac_id) === this.selectedHvacId)?.hvac_code },
      { label: 'Date', value: reportDate(this.selectedDate) }
    ];
  }

  /** Download the report as shown on the page, with the selected plant, system, unit and date at the top. */
  async downloadPdf(): Promise<void> {
    if (!this.reportRoot || !this.summary) {
      return;
    }
    this.plantContext = await firstValueFrom(this.plantContextService.forHvac(Number(this.selectedHvacId)));
    const unit = this.units.find((u) => String(u.hvac_id) === this.selectedHvacId)?.hvac_code ?? '';
    await this.report.download(this.reportRoot.nativeElement, {
      fileName: `Daily_HVAC_Summary_${fileSafe(this.plantContext.plant, 'Plant')}_${fileSafe(unit, 'Unit')}_${this.selectedDate}.pdf`,
      footer: `Daily HVAC Summary · ${this.plantContext.plant ?? ''} · ${unit} · ${this.selectedDate}`
    });
  }

  get metricCards(): MetricCard[] {
    const s = this.summary;
    return [
      { label: 'HVAC Energy Consumed', value: s?.energy_kwh ?? null, unit: 'kWh', decimals: 1, icon: 'plug' },
      { label: 'Peak HVAC Power', value: s?.peak_power_kw ?? null, unit: 'kW', decimals: 2, icon: 'power' },
      { label: 'Peak Heat Load', value: s?.max_heat_load_kw ?? null, unit: 'kW', decimals: 2, icon: 'heat' },
      { label: 'Avg COP (Cooling)', value: s?.avg_cop ?? null, unit: '', decimals: 2, icon: 'cop' },
      { label: 'Max Coolant Return Temp', value: s?.max_return_temp_c ?? null, unit: '°C', decimals: 1, icon: 'temp' },
      { label: 'Max Enclosure Temp', value: s?.max_enclosure_temp_c ?? null, unit: '°C', decimals: 1, icon: 'temp' },
      { label: 'Max Enclosure Humidity', value: s?.max_humidity_pct ?? null, unit: '%', decimals: 1, icon: 'humidity' },
      { label: 'Compressor Runtime', value: s?.cooling_hours ?? null, unit: 'h', decimals: 2, icon: 'clock' },
      { label: 'Compressor Duty Cycle', value: s?.compressor_duty_cycle_pct ?? null, unit: '%', decimals: 1, icon: 'duty' },
      { label: 'Cooling Time', value: s?.cooling_time_hours ?? null, unit: 'h', decimals: 2, icon: 'snow' }
    ];
  }

  onUnitChange(): void {
    if (!this.selectedHvacId) {
      return;
    }
    this.analyticsService.telemetryDateRange(Number(this.selectedHvacId)).subscribe({
      next: (range) => {
        this.minAvailableDate = range.min_date;
        this.maxAvailableDate = range.max_date;
        this.selectedDate = range.max_date ?? '';
        if (this.selectedDate) {
          this.loadAll();
        } else {
          this.summary = null;
          this.error = 'No HVAC telemetry data found for this unit.';
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
    this.analyticsService.dailySummary(Number(this.selectedHvacId), this.selectedDate).subscribe({
      next: (summary) => {
        this.summary = summary;
        this.loadingSummary = false;
      },
      error: () => {
        this.summary = null;
        this.loadingSummary = false;
        this.error = 'No HVAC telemetry data for this unit on the selected date.';
      }
    });
  }

  private loadCharts(): void {
    this.loadingCharts = true;
    const seriesStart = this.clampSeriesStart();
    const hvacId = Number(this.selectedHvacId);

    forkJoin({
      series: this.analyticsService.dailySeries(hvacId, seriesStart, this.maxAvailableDate ?? this.selectedDate)
    }).subscribe({
      next: ({ series }) => {
        this.loadingCharts = false;
        this.renderSeriesCharts(series);
      },
      error: () => {
        this.loadingCharts = false;
        this.error = 'Could not load chart data.';
      }
    });
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

  private renderSeriesCharts(series: HvacDailySummary[]): void {
    if (!this.viewReady) {
      return;
    }
    const labels = series.map((s) => s.date);

    this.upsertBarChart(
      'energy',
      this.energyChartRef,
      labels,
      [{ label: 'HVAC Energy (kWh)', data: series.map((s) => toNum(s.energy_kwh)), color: '#0e8f66' }],
      'Date',
      'Energy (kWh)'
    );

    this.upsertLineChart(
      'temp',
      this.tempChartRef,
      labels,
      [
        { label: 'Max Coolant Return Temp (°C)', data: series.map((s) => toNum(s.max_return_temp_c)), color: '#e5484d' },
        { label: 'Avg Ambient (°C)', data: series.map((s) => toNum(s.avg_ambient_c)), color: '#e08a1e' }
      ],
      'Date',
      'Temperature (°C)'
    );

    this.upsertLineChart(
      'cop',
      this.copChartRef,
      labels,
      [{ label: 'Avg COP', data: series.map((s) => toNum(s.avg_cop)), color: '#2f6fed' }],
      'Date',
      'COP'
    );
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
