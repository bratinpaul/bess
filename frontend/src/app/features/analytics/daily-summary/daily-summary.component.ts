import { CommonModule } from '@angular/common';
import { AfterViewInit, Component, ElementRef, OnDestroy, OnInit, ViewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute } from '@angular/router';
import { Chart, ChartConfiguration, registerables } from 'chart.js';
import { forkJoin } from 'rxjs';

import { DailySummary } from '../../../core/models/analytics.model';
import { BatterySystem } from '../../../core/models/battery-system.model';
import { SystemTelemetry } from '../../../core/models/system-telemetry.model';
import { AnalyticsService } from '../../../core/services/analytics.service';
import { BatterySystemService } from '../../../core/services/battery-system.service';
import { SystemTelemetryService } from '../../../core/services/system-telemetry.service';
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

type MetricIcon =
  | 'battery'
  | 'voltage'
  | 'charge'
  | 'discharge'
  | 'temperature'
  | 'imbalance'
  | 'efficiency'
  | 'cycles'
  | 'alarm'
  | 'health';

interface MetricCard {
  label: string;
  value: number | null;
  unit: string;
  decimals: number;
  icon: MetricIcon;
}

const MAX_SERIES_DAYS = 90;

@Component({
  selector: 'app-daily-summary',
  standalone: true,
  imports: [CommonModule, FormsModule, ReportHeaderComponent, PdfButtonComponent],
  templateUrl: './daily-summary.component.html',
  styleUrl: './daily-summary.component.scss'
})
export class DailySummaryComponent implements OnInit, AfterViewInit, OnDestroy {
  @ViewChild('socChart') socChartRef!: ElementRef<HTMLCanvasElement>;
  @ViewChild('voltageChart') voltageChartRef!: ElementRef<HTMLCanvasElement>;
  @ViewChild('currentChart') currentChartRef!: ElementRef<HTMLCanvasElement>;
  @ViewChild('tempChart') tempChartRef!: ElementRef<HTMLCanvasElement>;
  @ViewChild('throughputChart') throughputChartRef!: ElementRef<HTMLCanvasElement>;
  @ViewChild('cellVsAmbientChart') cellVsAmbientChartRef!: ElementRef<HTMLCanvasElement>;
  @ViewChild('sohChart') sohChartRef!: ElementRef<HTMLCanvasElement>;
  @ViewChild('powerChart') powerChartRef!: ElementRef<HTMLCanvasElement>;
  @ViewChild('cRateChart') cRateChartRef!: ElementRef<HTMLCanvasElement>;
  @ViewChild('cellTempChart') cellTempChartRef!: ElementRef<HTMLCanvasElement>;
  @ViewChild('coolantChart') coolantChartRef!: ElementRef<HTMLCanvasElement>;
  @ViewChild('reportRoot') reportRoot?: ElementRef<HTMLElement>;

  systems: BatterySystem[] = [];
  selectedSystemId: number | null = null;
  selectedDate = '';
  minAvailableDate: string | null = null;
  maxAvailableDate: string | null = null;

  summary: DailySummary | null = null;
  loadingSummary = false;
  loadingCharts = false;
  error: string | null = null;
  viewReady = false;

  /** PDF report state (Download PDF button). */
  readonly report = new ReportExporter();
  /** Plant and battery system of the selection (report header). */
  plantContext: PlantContext = { plant: null, system: null };

  private charts: Record<string, Chart> = {};

  constructor(
    private route: ActivatedRoute,
    private batterySystemService: BatterySystemService,
    private analyticsService: AnalyticsService,
    private telemetryService: SystemTelemetryService,
    private plantContextService: PlantContextService
  ) {}

  ngOnInit(): void {
    this.batterySystemService.list().subscribe({
      next: (systems) => {
        this.systems = systems;
        if (systems.length > 0) {
          // ?system=<battery_system_id> (e.g. from the Plant 3D View BMS panel) preselects that system
          const requested = Number(this.route.snapshot.queryParamMap.get('system'));
          const match = systems.find((s) => s.battery_system_id === requested);
          this.selectedSystemId = (match ?? systems[0]).battery_system_id;
          this.onSystemChange();
        }
      },
      error: () => {
        this.error = 'Could not load battery systems. Is the backend running?';
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

  get selectedSystem(): BatterySystem | undefined {
    return this.systems.find((s) => s.battery_system_id === this.selectedSystemId);
  }

  get canExport(): boolean {
    return !!this.summary && !this.loadingSummary && !this.loadingCharts && !this.error;
  }

  get reportFields(): ReportField[] {
    return [
      { label: 'Plant', value: this.plantContext.plant },
      { label: 'Battery System', value: this.selectedSystem?.system_name },
      { label: 'Date', value: reportDate(this.selectedDate) }
    ];
  }

  /** Download the report as shown on the page, with the selected plant, system and date at the top. */
  async downloadPdf(): Promise<void> {
    if (!this.canExport || !this.reportRoot) {
      return;
    }
    const system = this.selectedSystem?.system_name ?? '';
    await this.report.download(this.reportRoot.nativeElement, {
      fileName: `Daily_Battery_Summary_${fileSafe(this.plantContext.plant, 'Plant')}_${fileSafe(system, 'System')}_${this.selectedDate}.pdf`,
      footer: `Daily Battery Summary · ${this.plantContext.plant ?? ''} · ${system} · ${this.selectedDate}`
    });
  }

  get metricCards(): MetricCard[] {
    const s = this.summary;
    return [
      { label: 'Min SOC', value: s?.min_soc ?? null, unit: '%', decimals: 2, icon: 'battery' },
      { label: 'Max SOC', value: s?.max_soc ?? null, unit: '%', decimals: 2, icon: 'battery' },
      { label: 'Avg SOC', value: s?.avg_soc ?? null, unit: '%', decimals: 2, icon: 'battery' },
      { label: 'Min Pack Voltage', value: s?.min_pack_voltage ?? null, unit: 'V', decimals: 1, icon: 'voltage' },
      { label: 'Max Pack Voltage', value: s?.max_pack_voltage ?? null, unit: 'V', decimals: 1, icon: 'voltage' },
      { label: 'Peak Charge Power', value: s?.peak_charge_power ?? null, unit: 'kW', decimals: 1, icon: 'charge' },
      {
        label: 'Peak Discharge Power',
        value: s?.peak_discharge_power ?? null,
        unit: 'kW',
        decimals: 1,
        icon: 'discharge'
      },
      {
        label: 'Max Cell Temperature',
        value: s?.max_cell_temp ?? null,
        unit: '°C',
        decimals: 1,
        icon: 'temperature'
      },
      {
        label: 'Max Cell Imbalance',
        value: s?.max_cell_imbalance ?? null,
        unit: 'mV',
        decimals: 1,
        icon: 'imbalance'
      },
      {
        label: 'Total Energy Charged',
        value: s?.total_energy_charged ?? null,
        unit: 'kWh',
        decimals: 1,
        icon: 'charge'
      },
      {
        label: 'Total Energy Discharged',
        value: s?.total_energy_discharged ?? null,
        unit: 'kWh',
        decimals: 1,
        icon: 'discharge'
      },
      {
        label: 'DC Round-Trip Eff. (Terminal)',
        value: s?.round_trip_efficiency_pct ?? null,
        unit: '%',
        decimals: 1,
        icon: 'efficiency'
      },
      {
        label: 'Equivalent Full Cycles',
        value: s?.equiv_full_cycles ?? null,
        unit: '',
        decimals: 3,
        icon: 'cycles'
      },
      {
        label: 'Alarm Samples (Non-Normal)',
        value: s?.alarm_samples ?? null,
        unit: '',
        decimals: 0,
        icon: 'alarm'
      },
      { label: 'Ending SOH', value: s?.ending_soh ?? null, unit: '%', decimals: 2, icon: 'health' }
    ];
  }

  onSystemChange(): void {
    if (!this.selectedSystemId) {
      return;
    }
    this.plantContextService.forSystem(this.selectedSystemId).subscribe((c) => (this.plantContext = c));
    this.analyticsService.telemetryDateRange(this.selectedSystemId!).subscribe({
      next: (range) => {
        this.minAvailableDate = range.min_date;
        this.maxAvailableDate = range.max_date;
        this.selectedDate = range.max_date ?? '';
        if (this.selectedDate) {
          this.loadAll();
        } else {
          this.summary = null;
          this.error = 'No telemetry data found for this system.';
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
    this.analyticsService.dailySummary(this.selectedSystemId!, this.selectedDate).subscribe({
      next: (summary) => {
        this.summary = summary;
        this.loadingSummary = false;
      },
      error: () => {
        this.summary = null;
        this.loadingSummary = false;
        this.error = 'No telemetry data for this system on the selected date.';
      }
    });
  }

  private loadCharts(): void {
    this.loadingCharts = true;
    const dayStart = `${this.selectedDate}T00:00:00`;
    const dayEnd = `${this.selectedDate}T23:59:59`;

    const seriesStart = this.clampSeriesStart();
    const sohStart = this.minusDays(this.selectedDate, 6);

    forkJoin({
      intraday: this.telemetryService.list({
        systemId: this.selectedSystemId!,
        start: dayStart,
        end: dayEnd,
        page: 1,
        pageSize: 3000
      }),
      series: this.analyticsService.dailySeries(this.selectedSystemId!, seriesStart, this.maxAvailableDate ?? this.selectedDate),
      sohSeries: this.analyticsService.dailySeries(this.selectedSystemId!, sohStart, this.selectedDate)
    }).subscribe({
      next: ({ intraday, series, sohSeries }) => {
        const rows = [...intraday.items].sort((a, b) => a.ts.localeCompare(b.ts));
        this.loadingCharts = false;
        this.renderIntradayCharts(rows);
        this.renderSeriesCharts(series);
        this.renderSohChart(sohSeries);
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

  private renderIntradayCharts(rows: SystemTelemetry[]): void {
    if (!this.viewReady) {
      return;
    }
    const labels = rows.map((r) => this.formatTime(r.ts));

    this.upsertLineChart(
      'soc',
      this.socChartRef,
      labels,
      [{ label: 'SOC (%)', data: rows.map((r) => toNum(r.soc_bms_pct)), color: '#0e8f66' }],
      'Time',
      'SOC (%)'
    );
    this.upsertLineChart(
      'voltage',
      this.voltageChartRef,
      labels,
      [{ label: 'Pack Voltage (V)', data: rows.map((r) => toNum(r.pack_voltage_v)), color: '#2f6fed' }],
      'Time',
      'Pack Voltage (V)'
    );
    this.upsertLineChart(
      'current',
      this.currentChartRef,
      labels,
      [{ label: 'Pack Current (A)', data: rows.map((r) => toNum(r.pack_current_a)), color: '#e08a1e' }],
      'Time',
      'Pack Current (A)'
    );
    this.upsertLineChart(
      'temp',
      this.tempChartRef,
      labels,
      [{ label: 'Pack Temperature (°C)', data: rows.map((r) => toNum(r.cell_temp_avg_c)), color: '#e5484d' }],
      'Time',
      'Temperature (°C)'
    );
    this.upsertLineChart(
      'power',
      this.powerChartRef,
      labels,
      [{ label: 'Power (kW)', data: rows.map((r) => toNum(r.power_kw)), color: '#8046e5' }],
      'Time',
      'Power (kW)'
    );
    this.upsertLineChart(
      'cRate',
      this.cRateChartRef,
      labels,
      [{ label: 'C Rate', data: rows.map((r) => toNum(r.c_rate)), color: '#0e8f66' }],
      'Time',
      'C Rate'
    );
    this.upsertLineChart(
      'cellTemp',
      this.cellTempChartRef,
      labels,
      [
        { label: 'Min (°C)', data: rows.map((r) => toNum(r.cell_temp_min_c)), color: '#2f6fed' },
        { label: 'Avg (°C)', data: rows.map((r) => toNum(r.cell_temp_avg_c)), color: '#e08a1e' },
        { label: 'Max (°C)', data: rows.map((r) => toNum(r.cell_temp_max_c)), color: '#e5484d' }
      ],
      'Time',
      'Temperature (°C)'
    );
    this.upsertLineChart(
      'coolant',
      this.coolantChartRef,
      labels,
      [{ label: 'Coolant Temperature (°C)', data: rows.map((r) => toNum(r.coolant_temp_c)), color: '#2f6fed' }],
      'Time',
      'Temperature (°C)'
    );
  }

  private renderSohChart(series: DailySummary[]): void {
    if (!this.viewReady) {
      return;
    }
    const labels = series.map((s) => s.date);
    this.upsertLineChart(
      'soh',
      this.sohChartRef,
      labels,
      [{ label: 'Ending SOH (%)', data: series.map((s) => toNum(s.ending_soh)), color: '#0e8f66' }],
      'Date',
      'SOH (%)'
    );
  }

  private renderSeriesCharts(series: DailySummary[]): void {
    if (!this.viewReady) {
      return;
    }
    const labels = series.map((s) => s.date);

    this.upsertBarChart(
      'throughput',
      this.throughputChartRef,
      labels,
      [
        { label: 'Charged (kWh)', data: series.map((s) => toNum(s.total_energy_charged)), color: '#0e8f66' },
        { label: 'Discharged (kWh)', data: series.map((s) => toNum(s.total_energy_discharged)), color: '#e5484d' }
      ],
      'Date',
      'Energy (kWh)'
    );

    this.upsertLineChart(
      'cellVsAmbient',
      this.cellVsAmbientChartRef,
      labels,
      [
        { label: 'Max Cell Temp (°C)', data: series.map((s) => toNum(s.max_cell_temp)), color: '#e5484d' },
        { label: 'Avg Ambient (°C)', data: series.map((s) => toNum(s.avg_ambient_temp)), color: '#2f6fed' }
      ],
      'Date',
      'Temperature (°C)'
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
        datasets: datasets.map((d) => ({
          label: d.label,
          data: d.data,
          backgroundColor: d.color
        }))
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
