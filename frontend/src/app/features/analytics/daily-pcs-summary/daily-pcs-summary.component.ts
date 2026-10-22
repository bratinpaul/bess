import { CommonModule } from '@angular/common';
import { AfterViewInit, Component, ElementRef, inject, OnDestroy, OnInit, ViewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute } from '@angular/router';
import { Chart, ChartConfiguration, registerables } from 'chart.js';
import { firstValueFrom, forkJoin } from 'rxjs';

import { PcsDailySummary } from '../../../core/models/pcs-analytics.model';
import { Pcs } from '../../../core/models/pcs.model';
import { PcsTelemetry } from '../../../core/models/pcs-telemetry.model';
import { PcsAnalyticsService } from '../../../core/services/pcs-analytics.service';
import { PcsService } from '../../../core/services/pcs.service';
import { PcsTelemetryService } from '../../../core/services/pcs-telemetry.service';
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

type MetricIcon = 'charge' | 'discharge' | 'voltage' | 'gauge' | 'imbalance' | 'wave' | 'efficiency' | 'temperature' | 'alarm' | 'cycles';

interface MetricCard {
  label: string;
  value: number | null;
  unit: string;
  decimals: number;
  icon: MetricIcon;
}

const MAX_SERIES_DAYS = 90;

@Component({
  selector: 'app-daily-pcs-summary',
  standalone: true,
  imports: [CommonModule, FormsModule, ReportHeaderComponent, PdfButtonComponent],
  templateUrl: './daily-pcs-summary.component.html',
  styleUrl: './daily-pcs-summary.component.scss'
})
export class DailyPcsSummaryComponent implements OnInit, AfterViewInit, OnDestroy {
  @ViewChild('reportRoot') reportRoot?: ElementRef<HTMLElement>;
  /** PDF report state (Download PDF button). */
  readonly report = new ReportExporter();
  /** Plant and battery system of the selection (report header); resolved when a PDF is made. */
  plantContext: PlantContext = { plant: null, system: null };
  private plantContextService = inject(PlantContextService);

  @ViewChild('energyChart') energyChartRef!: ElementRef<HTMLCanvasElement>;
  @ViewChild('peakPowerChart') peakPowerChartRef!: ElementRef<HTMLCanvasElement>;
  @ViewChild('tempEffChart') tempEffChartRef!: ElementRef<HTMLCanvasElement>;
  @ViewChild('importExportChart') importExportChartRef!: ElementRef<HTMLCanvasElement>;
  @ViewChild('peakChargeChart') peakChargeChartRef!: ElementRef<HTMLCanvasElement>;
  @ViewChild('efficiencyChart') efficiencyChartRef!: ElementRef<HTMLCanvasElement>;

  pcsUnits: Pcs[] = [];
  selectedPcsId = '';
  selectedDate = '';
  minAvailableDate: string | null = null;
  maxAvailableDate: string | null = null;

  summary: PcsDailySummary | null = null;
  loadingSummary = false;
  loadingCharts = false;
  error: string | null = null;
  viewReady = false;

  private charts: Record<string, Chart> = {};

  private route = inject(ActivatedRoute);

  constructor(
    private pcsService: PcsService,
    private analyticsService: PcsAnalyticsService,
    private telemetryService: PcsTelemetryService
  ) {}

  ngOnInit(): void {
    this.pcsService.list().subscribe({
      next: (units) => {
        this.pcsUnits = units;
        if (units.length > 0) {
          // ?pcs=<id> (e.g. from the PCS pages) picks the PCS; otherwise the first one
          const requested = Number(this.route.snapshot.queryParamMap.get('pcs'));
          const unit = units.find((u) => u.pcs_id === requested) ?? units[0];
          this.selectedPcsId = String(unit.pcs_id);
          this.onPcsChange();
        }
      },
      error: () => {
        this.error = 'Could not load PCS units. Is the backend running?';
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
      { label: 'PCS', value: this.pcsUnits.find((u) => String(u.pcs_id) === this.selectedPcsId)?.pcs_code },
      { label: 'Date', value: reportDate(this.selectedDate) }
    ];
  }

  /** Download the report as shown on the page, with the selected plant, system, unit and date at the top. */
  async downloadPdf(): Promise<void> {
    if (!this.reportRoot || !this.summary) {
      return;
    }
    this.plantContext = await firstValueFrom(this.plantContextService.forPcs(Number(this.selectedPcsId)));
    const unit = this.pcsUnits.find((u) => String(u.pcs_id) === this.selectedPcsId)?.pcs_code ?? '';
    await this.report.download(this.reportRoot.nativeElement, {
      fileName: `Daily_PCS_Summary_${fileSafe(this.plantContext.plant, 'Plant')}_${fileSafe(unit, 'Unit')}_${this.selectedDate}.pdf`,
      footer: `Daily PCS Summary · ${this.plantContext.plant ?? ''} · ${unit} · ${this.selectedDate}`
    });
  }

  get metricCards(): MetricCard[] {
    const s = this.summary;
    return [
      { label: 'Peak Charge Power (AC)', value: s?.peak_charge_power_ac ?? null, unit: 'kW', decimals: 1, icon: 'charge' },
      { label: 'Peak Discharge Power (AC)', value: s?.peak_discharge_power_ac ?? null, unit: 'kW', decimals: 1, icon: 'discharge' },
      { label: 'Peak Apparent Power', value: s?.peak_apparent_power ?? null, unit: 'kVA', decimals: 1, icon: 'voltage' },
      { label: 'Min Power Factor', value: s?.min_power_factor ?? null, unit: '', decimals: 3, icon: 'gauge' },
      { label: 'Max Reactive Power', value: s?.max_reactive_power ?? null, unit: 'kvar', decimals: 1, icon: 'imbalance' },
      { label: 'Min AC Frequency (Closed)', value: s?.min_ac_frequency_closed ?? null, unit: 'Hz', decimals: 3, icon: 'wave' },
      { label: 'Max AC Frequency', value: s?.max_ac_frequency ?? null, unit: 'Hz', decimals: 3, icon: 'wave' },
      { label: 'Avg Efficiency (Converting)', value: s?.avg_efficiency ?? null, unit: '%', decimals: 2, icon: 'efficiency' },
      { label: 'Max IGBT Temperature', value: s?.max_igbt_temp ?? null, unit: '°C', decimals: 1, icon: 'temperature' },
      { label: 'Total Energy Imported (Charge)', value: s?.total_energy_imported ?? null, unit: 'kWh', decimals: 1, icon: 'charge' },
      { label: 'Total Energy Exported (Disch.)', value: s?.total_energy_exported ?? null, unit: 'kWh', decimals: 1, icon: 'discharge' },
      { label: 'AC-AC Round-Trip Eff.', value: s?.ac_ac_round_trip_eff_pct ?? null, unit: '%', decimals: 1, icon: 'efficiency' },
      { label: 'Alarm Samples (Level>0)', value: s?.alarm_samples ?? null, unit: '', decimals: 0, icon: 'alarm' },
      { label: 'VOLT_VAR Intervals', value: s?.volt_var_intervals ?? null, unit: '', decimals: 0, icon: 'cycles' },
      { label: 'FREQ_WATT Intervals', value: s?.freq_watt_intervals ?? null, unit: '', decimals: 0, icon: 'cycles' }
    ];
  }

  onPcsChange(): void {
    if (!this.selectedPcsId) {
      return;
    }
    this.analyticsService.telemetryDateRange(Number(this.selectedPcsId)).subscribe({
      next: (range) => {
        this.minAvailableDate = range.min_date;
        this.maxAvailableDate = range.max_date;
        this.selectedDate = range.max_date ?? '';
        if (this.selectedDate) {
          this.loadAll();
        } else {
          this.summary = null;
          this.error = 'No PCS telemetry data found for this unit.';
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
    this.analyticsService.dailySummary(Number(this.selectedPcsId), this.selectedDate).subscribe({
      next: (summary) => {
        this.summary = summary;
        this.loadingSummary = false;
      },
      error: () => {
        this.summary = null;
        this.loadingSummary = false;
        this.error = 'No PCS telemetry data for this unit on the selected date.';
      }
    });
  }

  private loadCharts(): void {
    this.loadingCharts = true;
    const dayStart = `${this.selectedDate}T00:00:00`;
    const dayEnd = `${this.selectedDate}T23:59:59`;
    const seriesStart = this.clampSeriesStart();

    forkJoin({
      intraday: this.telemetryService.list({
        pcsId: Number(this.selectedPcsId),
        start: dayStart,
        end: dayEnd,
        page: 1,
        pageSize: 3000
      }),
      series: this.analyticsService.dailySeries(
        Number(this.selectedPcsId),
        seriesStart,
        this.maxAvailableDate ?? this.selectedDate
      )
    }).subscribe({
      next: ({ intraday, series }) => {
        const rows = [...intraday.items].sort((a, b) => a.ts.localeCompare(b.ts));
        this.loadingCharts = false;
        this.renderIntradayCharts(rows);
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

  private renderIntradayCharts(rows: PcsTelemetry[]): void {
    if (!this.viewReady) {
      return;
    }
    const labels = rows.map((r) => this.formatTime(r.ts));

    this.upsertLineChart(
      'importExport',
      this.importExportChartRef,
      labels,
      [
        { label: 'Import (kWh)', data: rows.map((r) => toNum(r.ac_energy_import_kwh)), color: '#0e8f66' },
        { label: 'Export (kWh)', data: rows.map((r) => toNum(r.ac_energy_export_kwh)), color: '#e5484d' }
      ],
      'Time',
      'Energy (kWh)'
    );
    this.upsertLineChart(
      'peakCharge',
      this.peakChargeChartRef,
      labels,
      [{ label: 'AC Active Power (kW)', data: rows.map((r) => toNum(r.ac_active_power_kw)), color: '#8046e5' }],
      'Time',
      'AC Active Power (kW)'
    );
    this.upsertLineChart(
      'efficiency',
      this.efficiencyChartRef,
      labels,
      [{ label: 'Efficiency (%)', data: rows.map((r) => toNum(r.efficiency_pct)), color: '#2f6fed' }],
      'Time',
      'Efficiency (%)'
    );
  }

  private renderSeriesCharts(series: PcsDailySummary[]): void {
    if (!this.viewReady) {
      return;
    }
    const labels = series.map((s) => s.date);

    this.upsertBarChart(
      'energy',
      this.energyChartRef,
      labels,
      [
        { label: 'Imported (kWh)', data: series.map((s) => toNum(s.total_energy_imported)), color: '#0e8f66' },
        { label: 'Exported (kWh)', data: series.map((s) => toNum(s.total_energy_exported)), color: '#e5484d' }
      ],
      'Date',
      'Energy (kWh)'
    );

    this.upsertLineChart(
      'peakPower',
      this.peakPowerChartRef,
      labels,
      [
        { label: 'Peak Charge (kW)', data: series.map((s) => toNum(s.peak_charge_power_ac)), color: '#0e8f66' },
        { label: 'Peak Discharge (kW)', data: series.map((s) => toNum(s.peak_discharge_power_ac)), color: '#e5484d' }
      ],
      'Date',
      'Power (kW)'
    );

    this.upsertLineChart(
      'tempEff',
      this.tempEffChartRef,
      labels,
      [
        { label: 'Max IGBT Temp (°C)', data: series.map((s) => toNum(s.max_igbt_temp)), color: '#e5484d' },
        { label: 'Avg Efficiency (%)', data: series.map((s) => toNum(s.avg_efficiency)), color: '#2f6fed' }
      ],
      'Date',
      'Temperature (°C) / Efficiency (%)'
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
