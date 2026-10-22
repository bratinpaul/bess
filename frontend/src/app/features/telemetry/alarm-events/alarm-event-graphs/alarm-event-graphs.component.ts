import { CommonModule } from '@angular/common';
import { Component, EventEmitter, Input, OnChanges, Output } from '@angular/core';
import { ActiveElement, ChartConfiguration, ChartEvent, TooltipItem } from 'chart.js';

import { ALARM_SOURCES, AlarmSource } from '../../../../core/models/alarm-catalog.model';
import { AlarmEventAnalytics } from '../../../../core/models/alarm-event.model';
import { formatFull, timeAxis } from '../../graphs/time-axis';
import { ChartCanvasComponent } from '../../graphs/chart-canvas.component';
import { ChartOption } from '../../graphs/chart-selector.component';

/* Chart colours. Checked with the dataviz palette validator (lightness, chroma, colour-blind separation):
   - sources: the same hues as the source chips in the table;
   - severities: Info < Warning < Alarm < Critical (Alarm and Critical darkened from the badge colours so they
     stay apart when stacked); Warning is low-contrast on white, so every chart also carries labels/tooltips;
   - single-series and two-measure charts use violet / teal, which no source or severity uses. */
export const SOURCE_COLORS: Record<AlarmSource, string> = {
  BMS: '#0e8f66',
  PCS: '#b45309',
  HVAC: '#0369a1',
  EMS: '#be185d'
};
export const SEVERITY_COLORS = ['#3b82f6', '#d9a800', '#d9480f', '#9f1239'];
const PRIMARY = '#6d5bd0';
const SECONDARY = '#2aa198';
const REMAINDER = '#cdd2d9';

const INK_MUTED = '#6b6f76';
const GRID = 'rgba(0, 0, 0, 0.06)';
const SURFACE = '#ffffff';

type AnyConfig = ChartConfiguration;

function shortDate(iso: string): string {
  // 'YYYY-MM-DD' read as a calendar date (no time-zone shift)
  const [y, m, d] = iso.split('-').map(Number);
  return new Date(y, m - 1, d).toLocaleDateString([], { day: '2-digit', month: 'short' });
}

/** Plant local time ('YYYY-MM-DDTHH:mm:ss+05:30') as a local clock reading, like the table shows it. */
function plantMs(iso: string): number {
  return new Date(iso.slice(0, 19)).getTime();
}

function minutesLabel(minutes: number | null | undefined): string {
  if (minutes === null || minutes === undefined) {
    return '—';
  }
  if (minutes < 60) {
    return `${Math.round(minutes)} min`;
  }
  const h = Math.floor(minutes / 60);
  const m = Math.round(minutes % 60);
  return m ? `${h} h ${m} min` : `${h} h`;
}

function tooltipBase() {
  return {
    backgroundColor: '#26282b',
    titleFont: { weight: 'bold' as const, size: 12 },
    bodyFont: { size: 12 },
    padding: 10,
    boxPadding: 4,
    cornerRadius: 6
  };
}

function countAxis(title?: string) {
  return {
    beginAtZero: true,
    grace: '12%',
    ticks: { precision: 0, color: INK_MUTED, font: { size: 11 } },
    grid: { color: GRID },
    border: { display: false },
    title: { display: !!title, text: title ?? '', color: INK_MUTED, font: { size: 11 } }
  };
}

function categoryAxis() {
  return {
    ticks: { color: INK_MUTED, font: { size: 11 } },
    grid: { display: false },
    border: { color: '#d7d9dc' }
  };
}

function legend(show: boolean) {
  return {
    display: show,
    position: 'top' as const,
    align: 'end' as const,
    labels: { usePointStyle: true, pointStyle: 'rectRounded', boxWidth: 10, boxHeight: 10, color: '#52565c', font: { size: 12 } }
  };
}

function pointerOnHover(event: ChartEvent, elements: ActiveElement[]): void {
  const target = event.native?.target as HTMLElement | undefined;
  if (target) {
    target.style.cursor = elements.length ? 'pointer' : 'default';
  }
}

/** The charts on this tab, for the chart selector (ids match the chart configs below). */
export const ALARM_CHART_OPTIONS: ChartOption[] = [
  { id: 'daily', title: 'Alarms per day', meta: 'Stacked bar · by severity' },
  { id: 'bySource', title: 'Alarms by source', meta: 'Bar · BMS, PCS, HVAC, EMS' },
  { id: 'bySeverity', title: 'Alarms by severity', meta: 'Bar · Info to Critical' },
  { id: 'topCodes', title: 'Top alarm codes', meta: 'Bar · 10 most frequent' },
  { id: 'byType', title: 'Alarms by type', meta: 'Bar · per alarm type' },
  { id: 'topAssets', title: 'Assets with the most alarms', meta: 'Bar · top 10 assets' },
  { id: 'hourOfDay', title: 'Alarms by time of day', meta: 'Bar · hour of day' },
  { id: 'clearTime', title: 'Time to clear by source', meta: 'Bar · mean & longest' },
  { id: 'acknowledgement', title: 'Acknowledgement by severity', meta: 'Stacked bar · acknowledged or not' },
  { id: 'durations', title: 'Alarm duration over time', meta: 'Scatter · each cleared alarm' }
];

@Component({
  selector: 'app-alarm-event-graphs',
  standalone: true,
  imports: [CommonModule, ChartCanvasComponent],
  templateUrl: './alarm-event-graphs.component.html',
  styleUrl: '../../graphs/graph-grid.scss'
})
export class AlarmEventGraphsComponent implements OnChanges {
  @Input() analytics: AlarmEventAnalytics | null = null;
  @Input() loading = false;
  @Input() error: string | null = null;
  /** Charts unticked in the chart selector. */
  @Input() hidden: Set<string> = new Set();
  /** Clicking a bar narrows the page's filters. */
  @Output() sourceSelect = new EventEmitter<string>();
  @Output() severitySelect = new EventEmitter<number>();
  @Output() daySelect = new EventEmitter<string>();
  @Output() alarmOpen = new EventEmitter<string>();

  readonly sourceLegend = ALARM_SOURCES.map((s) => ({ label: s, color: SOURCE_COLORS[s] }));

  daily?: AnyConfig;
  bySource?: AnyConfig;
  bySeverity?: AnyConfig;
  byType?: AnyConfig;
  topCodes?: AnyConfig;
  topAssets?: AnyConfig;
  hourOfDay?: AnyConfig;
  clearTime?: AnyConfig;
  acknowledgement?: AnyConfig;
  durations?: AnyConfig;

  typeHeight = 260;
  codesHeight = 260;
  assetsHeight = 260;

  // headline figures shown in the card subtitles
  peakDay: { date: string; count: number } | null = null;
  peakHour: { hour: number; count: number } | null = null;
  topShare = 0;
  ackRate = 0;

  shown(id: string): boolean {
    return !this.hidden.has(id);
  }

  ngOnChanges(): void {
    const a = this.analytics;
    if (!a || a.total === 0) {
      return;
    }
    this.buildDaily(a);
    this.buildBySource(a);
    this.buildBySeverity(a);
    this.buildByType(a);
    this.buildTopCodes(a);
    this.buildTopAssets(a);
    this.buildHourOfDay(a);
    this.buildClearTime(a);
    this.buildAcknowledgement(a);
    this.buildDurations(a);
  }

  sourceColor(source: string): string {
    return SOURCE_COLORS[source as AlarmSource] ?? PRIMARY;
  }

  formatDay(iso: string): string {
    return shortDate(iso);
  }

  hourLabel(hour: number): string {
    return `${String(hour).padStart(2, '0')}:00–${String((hour + 1) % 24).padStart(2, '0')}:00`;
  }

  // ---------------------------------------------------------------- builders

  private buildDaily(a: AlarmEventAnalytics): void {
    const totals = a.daily.map((d) => d.by_severity.reduce((s, n) => s + n, 0));
    const peak = totals.reduce((best, n, i) => (n > totals[best] ? i : best), 0);
    this.peakDay = a.daily.length ? { date: a.daily[peak].date, count: totals[peak] } : null;
    this.daily = {
      type: 'bar',
      data: {
        labels: a.daily.map((d) => shortDate(d.date)),
        datasets: a.by_severity.map((sev, i) => ({
          label: sev.severity_name,
          data: a.daily.map((d) => d.by_severity[i] ?? 0),
          backgroundColor: SEVERITY_COLORS[sev.severity_level] ?? PRIMARY,
          borderColor: SURFACE,
          borderWidth: { top: 2, bottom: 0, left: 0, right: 0 },
          borderSkipped: false,
          borderRadius: 2,
          maxBarThickness: 22
        }))
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        onHover: pointerOnHover,
        onClick: (_e, elements) => {
          if (elements.length) {
            this.daySelect.emit(a.daily[elements[0].index].date);
          }
        },
        scales: {
          x: { ...categoryAxis(), stacked: true, ticks: { ...categoryAxis().ticks, maxRotation: 0, autoSkipPadding: 12 } },
          y: { ...countAxis('Alarms started'), stacked: true }
        },
        plugins: {
          legend: legend(true),
          tooltip: {
            ...tooltipBase(),
            filter: (item: TooltipItem<'bar'>) => Number(item.raw) > 0,
            callbacks: {
              title: (items: TooltipItem<'bar'>[]) => (items.length ? shortDate(a.daily[items[0].dataIndex].date) : ''),
              footer: (items: TooltipItem<'bar'>[]) =>
                items.length ? `Total ${totals[items[0].dataIndex]} · click to filter this day` : ''
            }
          }
        }
      }
    } as AnyConfig;
  }

  private buildBySource(a: AlarmEventAnalytics): void {
    this.bySource = {
      type: 'bar',
      data: {
        labels: a.by_source.map((s) => s.key),
        datasets: [{
          label: 'Alarms',
          data: a.by_source.map((s) => s.count),
          backgroundColor: a.by_source.map((s) => this.sourceColor(s.key)),
          borderRadius: 4,
          borderSkipped: 'start',
          maxBarThickness: 56
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        onHover: pointerOnHover,
        onClick: (_e, elements) => {
          if (elements.length) {
            this.sourceSelect.emit(a.by_source[elements[0].index].key);
          }
        },
        scales: { x: categoryAxis(), y: countAxis() },
        plugins: {
          legend: legend(false),
          valueLabels: { format: (v: number) => `${v}` },
          tooltip: {
            ...tooltipBase(),
            callbacks: {
              label: (item: TooltipItem<'bar'>) =>
                ` ${item.raw} alarms · ${Math.round((100 * Number(item.raw)) / a.total)}% of total`,
              footer: () => 'Click to filter by this source'
            }
          }
        }
      }
    } as AnyConfig;
  }

  private buildBySeverity(a: AlarmEventAnalytics): void {
    this.bySeverity = {
      type: 'bar',
      data: {
        labels: a.by_severity.map((s) => s.severity_name),
        datasets: [{
          label: 'Alarms',
          data: a.by_severity.map((s) => s.count),
          backgroundColor: a.by_severity.map((s) => SEVERITY_COLORS[s.severity_level] ?? PRIMARY),
          borderRadius: 4,
          borderSkipped: 'start',
          maxBarThickness: 56
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        onHover: pointerOnHover,
        onClick: (_e, elements) => {
          if (elements.length) {
            this.severitySelect.emit(a.by_severity[elements[0].index].severity_level);
          }
        },
        scales: { x: categoryAxis(), y: countAxis() },
        plugins: {
          legend: legend(false),
          valueLabels: { format: (v: number) => `${v}` },
          tooltip: {
            ...tooltipBase(),
            callbacks: {
              label: (item: TooltipItem<'bar'>) =>
                ` ${item.raw} alarms · ${Math.round((100 * Number(item.raw)) / a.total)}% of total`,
              footer: () => 'Click to filter by this severity'
            }
          }
        }
      }
    } as AnyConfig;
  }

  private horizontalBar(
    labels: string[],
    values: number[],
    colors: string | string[],
    format: (v: number, i: number) => string,
    tooltip: Record<string, unknown>
  ): AnyConfig {
    return {
      type: 'bar',
      data: {
        labels,
        datasets: [{
          label: 'Alarms',
          data: values,
          backgroundColor: colors,
          borderRadius: 4,
          borderSkipped: 'start',
          barPercentage: 0.8,
          categoryPercentage: 0.85,
          maxBarThickness: 18
        }]
      },
      options: {
        indexAxis: 'y',
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: { ...countAxis(), grace: '22%' },
          y: { ...categoryAxis(), ticks: { ...categoryAxis().ticks, autoSkip: false } }
        },
        plugins: {
          legend: legend(false),
          valueLabels: { format },
          tooltip: { ...tooltipBase(), callbacks: tooltip }
        }
      }
    } as AnyConfig;
  }

  private buildByType(a: AlarmEventAnalytics): void {
    this.typeHeight = Math.max(200, a.by_type.length * 24 + 40);
    this.byType = this.horizontalBar(
      a.by_type.map((t) => t.key),
      a.by_type.map((t) => t.count),
      PRIMARY,
      (v) => `${v}`,
      {
        label: (item: TooltipItem<'bar'>) =>
          ` ${item.raw} alarms · ${Math.round((100 * Number(item.raw)) / a.total)}% of total`
      }
    );
  }

  private buildTopCodes(a: AlarmEventAnalytics): void {
    const codes = a.top_codes;
    this.topShare = Math.round(codes.slice(0, 3).reduce((s, c) => s + c.share_pct, 0));
    this.codesHeight = Math.max(200, codes.length * 26 + 40);
    this.topCodes = this.horizontalBar(
      codes.map((c) => c.alarm_code),
      codes.map((c) => c.count),
      codes.map((c) => this.sourceColor(c.source)),
      (v, i) => `${v} · ${codes[i].share_pct}%`,
      {
        title: (items: TooltipItem<'bar'>[]) => (items.length ? `${codes[items[0].dataIndex].source} · ${codes[items[0].dataIndex].alarm_code}` : ''),
        label: (item: TooltipItem<'bar'>) => ` ${item.raw} alarms · ${codes[item.dataIndex].share_pct}% of total`,
        afterLabel: (item: TooltipItem<'bar'>) => {
          const c = codes[item.dataIndex];
          return [c.description ?? '', `Mean duration ${minutesLabel(c.mean_duration_min)}`].filter(Boolean);
        }
      }
    );
  }

  private buildTopAssets(a: AlarmEventAnalytics): void {
    const assets = a.top_assets;
    this.assetsHeight = Math.max(200, assets.length * 26 + 40);
    this.topAssets = this.horizontalBar(
      assets.map((x) => x.asset_name),
      assets.map((x) => x.count),
      assets.map((x) => this.sourceColor(x.source)),
      (v) => `${v}`,
      {
        title: (items: TooltipItem<'bar'>[]) => (items.length ? assets[items[0].dataIndex].asset_name : ''),
        label: (item: TooltipItem<'bar'>) => {
          const x = assets[item.dataIndex];
          return ` ${item.raw} alarms · ${x.asset_type ?? 'Asset'} · ${x.source}`;
        }
      }
    );
  }

  private buildHourOfDay(a: AlarmEventAnalytics): void {
    const hours = a.hour_of_day;
    const peak = hours.reduce((best, n, i) => (n > hours[best] ? i : best), 0);
    this.peakHour = { hour: peak, count: hours[peak] };
    this.hourOfDay = {
      type: 'bar',
      data: {
        labels: hours.map((_, h) => String(h).padStart(2, '0')),
        datasets: [{
          label: 'Alarms',
          data: hours,
          backgroundColor: PRIMARY,
          borderRadius: 3,
          borderSkipped: 'start',
          barPercentage: 0.85,
          categoryPercentage: 0.9
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: { ...categoryAxis(), title: { display: true, text: 'Hour of day (plant time)', color: INK_MUTED, font: { size: 11 } } },
          y: countAxis()
        },
        plugins: {
          legend: legend(false),
          tooltip: {
            ...tooltipBase(),
            callbacks: {
              title: (items: TooltipItem<'bar'>[]) => (items.length ? this.hourLabel(items[0].dataIndex) : ''),
              label: (item: TooltipItem<'bar'>) => ` ${item.raw} alarms started`
            }
          }
        }
      }
    } as AnyConfig;
  }

  private buildClearTime(a: AlarmEventAnalytics): void {
    const rows = a.duration_by_source;
    const bar = (label: string, data: (number | null)[], color: string) => ({
      label,
      data,
      backgroundColor: color,
      borderRadius: 4,
      borderSkipped: 'start' as const,
      maxBarThickness: 30
    });
    this.clearTime = {
      type: 'bar',
      data: {
        labels: rows.map((r) => r.source),
        datasets: [
          bar('Mean', rows.map((r) => r.mean_duration_min), PRIMARY),
          bar('Longest', rows.map((r) => r.max_duration_min), SECONDARY)
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: { x: categoryAxis(), y: countAxis('Minutes to clear') },
        plugins: {
          legend: legend(true),
          valueLabels: { format: (v: number) => `${Math.round(v)}` },
          tooltip: {
            ...tooltipBase(),
            callbacks: {
              label: (item: TooltipItem<'bar'>) => ` ${item.dataset.label}: ${minutesLabel(Number(item.raw))}`,
              footer: (items: TooltipItem<'bar'>[]) =>
                items.length ? `${rows[items[0].dataIndex].cleared} cleared alarms` : ''
            }
          }
        }
      }
    } as AnyConfig;
  }

  private buildAcknowledgement(a: AlarmEventAnalytics): void {
    const rows = a.by_severity;
    const acked = rows.reduce((s, r) => s + r.acknowledged, 0);
    this.ackRate = a.total ? Math.round((100 * acked) / a.total) : 0;
    const part = (label: string, data: number[], color: string) => ({
      label,
      data,
      backgroundColor: color,
      borderColor: SURFACE,
      borderWidth: { top: 0, bottom: 0, left: 0, right: 2 },
      borderSkipped: false,
      borderRadius: 2,
      maxBarThickness: 22
    });
    this.acknowledgement = {
      type: 'bar',
      data: {
        labels: rows.map((r) => r.severity_name),
        datasets: [
          part('Acknowledged', rows.map((r) => r.acknowledged), PRIMARY),
          part('Not acknowledged', rows.map((r) => r.count - r.acknowledged), REMAINDER)
        ]
      },
      options: {
        indexAxis: 'y',
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        scales: {
          x: { ...countAxis(), stacked: true, grace: 0 },
          y: { ...categoryAxis(), stacked: true }
        },
        plugins: {
          legend: legend(true),
          tooltip: {
            ...tooltipBase(),
            callbacks: {
              label: (item: TooltipItem<'bar'>) => ` ${item.dataset.label}: ${item.raw}`,
              footer: (items: TooltipItem<'bar'>[]) => {
                if (!items.length) {
                  return '';
                }
                const r = rows[items[0].dataIndex];
                const pct = r.count ? Math.round((100 * r.acknowledged) / r.count) : 0;
                return `${pct}% acknowledged · mean time to acknowledge ${minutesLabel(r.mean_minutes_to_ack)}`;
              }
            }
          }
        }
      }
    } as AnyConfig;
  }

  private buildDurations(a: AlarmEventAnalytics): void {
    const points = a.durations;
    if (!points.length) {
      this.durations = undefined;
      return;
    }
    const xs = points.map((p) => plantMs(p.start_time));
    const pad = 6 * 3600_000;
    const xMin = Math.min(...xs) - pad;
    const xMax = Math.max(...xs) + pad;
    const levels = a.by_severity.map((s) => s.severity_level);
    this.durations = {
      type: 'scatter',
      data: {
        datasets: a.by_severity.map((sev) => {
          const mine = points.filter((p) => p.severity_level === sev.severity_level);
          return {
            label: sev.severity_name,
            data: mine.map((p) => ({ x: plantMs(p.start_time), y: p.duration_min, alarm: p })),
            backgroundColor: SEVERITY_COLORS[sev.severity_level] ?? PRIMARY,
            borderColor: SURFACE,
            borderWidth: 1.5,
            pointRadius: 5,
            pointHoverRadius: 7,
            pointHitRadius: 8
          };
        })
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        onHover: pointerOnHover,
        onClick: (_e, elements) => {
          if (elements.length) {
            const el = elements[0];
            const sev = levels[el.datasetIndex];
            const mine = points.filter((p) => p.severity_level === sev);
            this.alarmOpen.emit(mine[el.index].alarm_id);
          }
        },
        scales: {
          x: { ...timeAxis(xMin, xMax), ticks: { ...timeAxis(xMin, xMax).ticks, color: INK_MUTED, font: { size: 11 } } },
          y: { ...countAxis('Duration (min)'), ticks: { color: INK_MUTED, font: { size: 11 } } }
        },
        plugins: {
          legend: legend(true),
          tooltip: {
            ...tooltipBase(),
            callbacks: {
              title: (items: TooltipItem<'scatter'>[]) => {
                const p = (items[0]?.raw as { alarm?: (typeof points)[number] })?.alarm;
                return p ? `${p.alarm_id} · ${p.source} ${p.alarm_code}` : '';
              },
              label: (item: TooltipItem<'scatter'>) => {
                const p = (item.raw as { alarm: (typeof points)[number] }).alarm;
                return [` ${item.dataset.label}, lasted ${minutesLabel(p.duration_min)}`, ` Started ${formatFull(plantMs(p.start_time))}`];
              },
              footer: () => 'Click to open the alarm'
            }
          }
        }
      }
    } as AnyConfig;
  }
}
