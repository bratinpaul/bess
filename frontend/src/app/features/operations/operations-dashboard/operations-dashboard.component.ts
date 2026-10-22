import { CommonModule } from '@angular/common';
import { AfterViewInit, Component, ElementRef, OnDestroy, OnInit, ViewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Chart, ChartConfiguration, registerables } from 'chart.js';
import { forkJoin } from 'rxjs';

import { DailySummary } from '../../../core/models/analytics.model';
import { BatterySystem } from '../../../core/models/battery-system.model';
import { OperationsOverview } from '../../../core/models/operations.model';
import { PcsDailySummary } from '../../../core/models/pcs-analytics.model';
import { Pcs } from '../../../core/models/pcs.model';
import { AnalyticsService } from '../../../core/services/analytics.service';
import { BatterySystemService } from '../../../core/services/battery-system.service';
import { OperationsService } from '../../../core/services/operations.service';
import { PcsAnalyticsService } from '../../../core/services/pcs-analytics.service';
import { PcsService } from '../../../core/services/pcs.service';

Chart.register(...registerables);

function toNum(value: unknown): number | null {
  if (value === null || value === undefined || value === '') {
    return null;
  }
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

const PERIOD_OPTIONS = [7, 14, 30, 90];

@Component({
  selector: 'app-operations-dashboard',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './operations-dashboard.component.html',
  styleUrl: './operations-dashboard.component.scss'
})
export class OperationsDashboardComponent implements OnInit, AfterViewInit, OnDestroy {
  @ViewChild('powerChart') powerChartRef!: ElementRef<HTMLCanvasElement>;
  @ViewChild('socSohChart') socSohChartRef!: ElementRef<HTMLCanvasElement>;
  @ViewChild('alarmsChart') alarmsChartRef!: ElementRef<HTMLCanvasElement>;

  systems: BatterySystem[] = [];
  pcsUnits: Pcs[] = [];
  selectedSystemId: number | null = null;
  periodOptions = PERIOD_OPTIONS;
  selectedDays = 30;

  overview: OperationsOverview | null = null;
  loading = true;
  loadingCharts = false;
  error: string | null = null;
  viewReady = false;

  private charts: Record<string, Chart> = {};

  constructor(
    private batterySystemService: BatterySystemService,
    private operationsService: OperationsService,
    private bmsAnalyticsService: AnalyticsService,
    private pcsAnalyticsService: PcsAnalyticsService,
    private pcsService: PcsService
  ) {}

  ngOnInit(): void {
    forkJoin({
      systems: this.batterySystemService.list(),
      pcsUnits: this.pcsService.list()
    }).subscribe({
      next: ({ systems, pcsUnits }) => {
        this.systems = systems;
        this.pcsUnits = pcsUnits;
        if (systems.length > 0) {
          this.selectedSystemId = systems[0].battery_system_id;
          this.load();
        } else {
          this.loading = false;
        }
      },
      error: () => {
        this.error = 'Could not load battery systems. Is the backend running?';
        this.loading = false;
      }
    });
  }

  ngAfterViewInit(): void {
    this.viewReady = true;
    if (this.overview) {
      this.loadCharts();
    }
  }

  ngOnDestroy(): void {
    Object.values(this.charts).forEach((chart) => chart.destroy());
  }

  get isHealthy(): boolean {
    const latest = this.overview?.latest;
    return !latest?.bms_alarm_level && !latest?.pcs_alarm_level;
  }

  get peakPowerMagnitudeKw(): number | null {
    const v = this.overview?.period.peak_discharge_power_ac_kw;
    if (v === null || v === undefined) return null;
    return Math.abs(v);
  }

  get availabilityBadge(): string {
    const pct = this.overview?.period.availability_pct;
    if (pct === null || pct === undefined) return '—';
    if (pct >= 99) return 'Healthy';
    if (pct >= 95) return 'Degraded';
    return 'At Risk';
  }

  onFilterChange(): void {
    this.load();
  }

  private load(): void {
    if (!this.selectedSystemId) {
      return;
    }
    this.loading = true;
    this.error = null;
    this.operationsService.overview(this.selectedSystemId!, this.selectedDays).subscribe({
      next: (overview) => {
        this.overview = overview;
        this.loading = false;
        this.loadCharts();
      },
      error: () => {
        this.overview = null;
        this.loading = false;
        this.error = 'No telemetry data available for this system.';
      }
    });
  }

  private loadCharts(): void {
    if (!this.overview) {
      return;
    }
    this.loadingCharts = true;
    const { start_date, end_date } = this.overview.period;
    const systemId = this.overview.system_id;

    const firstPcs = this.pcsUnits.find((unit) => unit.system_id === systemId);

    forkJoin({
      bmsSeries: this.bmsAnalyticsService.dailySeries(systemId, start_date, end_date),
      pcsSeries: firstPcs
        ? this.pcsAnalyticsService.dailySeries(firstPcs.pcs_id, start_date, end_date)
        : Promise.resolve([] as PcsDailySummary[])
    }).subscribe({
      next: ({ bmsSeries, pcsSeries }) => {
        this.loadingCharts = false;
        this.renderCharts(bmsSeries, pcsSeries as PcsDailySummary[]);
      },
      error: () => {
        this.loadingCharts = false;
      }
    });
  }

  private renderCharts(bmsSeries: DailySummary[], pcsSeries: PcsDailySummary[]): void {
    if (!this.viewReady) {
      return;
    }
    const labels = bmsSeries.map((s) => s.date);

    this.upsertLineChart(
      'power',
      this.powerChartRef,
      labels,
      [
        { label: 'Peak Charge (kW)', data: pcsSeries.map((s) => toNum(s.peak_charge_power_ac)), color: '#0e8f66' },
        { label: 'Peak Discharge (kW)', data: pcsSeries.map((s) => toNum(s.peak_discharge_power_ac)), color: '#e5484d' }
      ],
      'Date',
      'Power (kW)'
    );

    this.upsertLineChart(
      'socSoh',
      this.socSohChartRef,
      labels,
      [
        { label: 'Avg SOC (%)', data: bmsSeries.map((s) => toNum(s.avg_soc)), color: '#2f6fed' },
        { label: 'Ending SOH (%)', data: bmsSeries.map((s) => toNum(s.ending_soh)), color: '#0e8f66' }
      ],
      'Date',
      'Percent (%)'
    );

    this.upsertBarChart(
      'alarms',
      this.alarmsChartRef,
      labels,
      [
        { label: 'BMS Alarms', data: bmsSeries.map((s) => toNum(s.alarm_samples)), color: '#e08a1e' },
        { label: 'PCS Alarms', data: pcsSeries.map((s) => toNum(s.alarm_samples)), color: '#e5484d' }
      ],
      'Date',
      'Alarm Count'
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
