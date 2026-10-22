import { CommonModule } from '@angular/common';
import { Component, EventEmitter, Input, OnChanges, Output } from '@angular/core';
import { ActiveElement, ChartConfiguration, ChartEvent, ScriptableLineSegmentContext, TooltipItem } from 'chart.js';

import {
  DispatchEventAnalytics,
  DispatchPoint,
  MODE_COLORS,
  MODE_ORDER,
  modeLabel
} from '../../../../core/models/dispatch-event.model';
import { ChartCanvasComponent } from '../../graphs/chart-canvas.component';
import { ChartOption } from '../../graphs/chart-selector.component';
import { formatFull, timeAxis } from '../../graphs/time-axis';

/* Colours (checked with the dataviz palette validator):
   - modes: MODE_COLORS, stacked in MODE_ORDER so neighbours stay distinguishable;
   - charge / discharge: the green / brown the list page uses for the setpoint;
   - single measures (revenue, price, counts) use one neutral ink - the title names the series. */
const CHARGE = '#0e8f66';
const DISCHARGE = '#b45309';
const INK = '#475569';
const INK_LIGHT = '#94a3b8';
const INK_MUTED = '#6b6f76';
const GRID = 'rgba(0, 0, 0, 0.06)';
const SURFACE = '#ffffff';

type AnyConfig = ChartConfiguration;

function shortDate(iso: string): string {
  const [y, m, d] = iso.split('-').map(Number);
  return new Date(y, m - 1, d).toLocaleDateString([], { day: '2-digit', month: 'short' });
}

/** Plant local time ('YYYY-MM-DDTHH:mm:ss+05:30') as a local clock reading, like the table shows it. */
function plantMs(iso: string): number {
  return new Date(iso.slice(0, 19)).getTime();
}

function withAlpha(hex: string, alpha: number): string {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
}

const usd = (v: number, digits = 0) =>
  (v < 0 ? '-$' : '$') + Math.abs(v).toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
const kwh = (v: number) => `${Math.round(Math.abs(v)).toLocaleString()} kWh`;

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

function valueAxis(title?: string, extra: Record<string, unknown> = {}) {
  return {
    grace: '8%',
    ticks: { color: INK_MUTED, font: { size: 11 } },
    grid: { color: GRID },
    border: { display: false },
    title: { display: !!title, text: title ?? '', color: INK_MUTED, font: { size: 11 } },
    ...extra
  };
}

function categoryAxis(extra: Record<string, unknown> = {}) {
  return {
    ticks: { color: INK_MUTED, font: { size: 11 }, maxRotation: 0, autoSkipPadding: 10 },
    grid: { display: false },
    border: { color: '#d7d9dc' },
    ...extra
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
export const DISPATCH_CHART_OPTIONS: ChartOption[] = [
  { id: 'dailyRevenue', title: 'Daily market revenue ($)', meta: 'Line · USD per day' },
  { id: 'eventsByMode', title: 'Events by dispatch mode', meta: 'Bar · per mode' },
  { id: 'dailyEvents', title: 'Daily dispatch events', meta: 'Stacked bar · by mode' },
  { id: 'modeHours', title: 'Time in each mode per day', meta: 'Stacked bar · hours' },
  { id: 'dailyEnergy', title: 'Daily energy charged vs discharged', meta: 'Diverging bar · kWh' },
  { id: 'hourlyEnergy', title: 'Charge & discharge by hour of day', meta: 'Diverging bar · kWh by hour' },
  { id: 'hourlyPrice', title: 'Average market price by hour of day', meta: 'Bar · $/MWh by hour' },
  { id: 'setpoint', title: 'Power setpoint schedule', meta: 'Step line · kW' },
  { id: 'soc', title: 'SOC through the dispatches', meta: 'Line · SOC & target SOC' },
  { id: 'priceScatter', title: 'Setpoint vs market price', meta: 'Scatter · each dispatch' },
  { id: 'revenueByMode', title: 'Revenue by dispatch mode', meta: 'Bar · USD per mode' },
  { id: 'energyByMode', title: 'Energy by dispatch mode', meta: 'Bar · MWh charged & discharged' },
  { id: 'durationByMode', title: 'Dispatch duration by mode', meta: 'Bar · mean minutes' },
  { id: 'cumulativeRevenue', title: 'Cumulative market revenue', meta: 'Line · running total' },
  { id: 'issuers', title: 'Dispatches by issuer', meta: 'Bar · per issuer' }
];

@Component({
  selector: 'app-dispatch-event-graphs',
  standalone: true,
  imports: [CommonModule, ChartCanvasComponent],
  templateUrl: './dispatch-event-graphs.component.html',
  styleUrl: '../../graphs/graph-grid.scss'
})
export class DispatchEventGraphsComponent implements OnChanges {
  @Input() analytics: DispatchEventAnalytics | null = null;
  @Input() loading = false;
  @Input() error: string | null = null;
  /** Charts unticked in the chart selector. */
  @Input() hidden: Set<string> = new Set();
  /** Clicking a chart narrows the page's filters, or opens a dispatch. */
  @Output() modeSelect = new EventEmitter<string>();
  @Output() daySelect = new EventEmitter<string>();
  @Output() dispatchOpen = new EventEmitter<string>();

  modeLabel = modeLabel;
  modeLegend: { code: string; label: string; color: string }[] = [];

  dailyRevenue?: AnyConfig;
  cumulativeRevenue?: AnyConfig;
  eventsByMode?: AnyConfig;
  dailyEvents?: AnyConfig;
  modeHours?: AnyConfig;
  dailyEnergy?: AnyConfig;
  hourlyEnergy?: AnyConfig;
  hourlyPrice?: AnyConfig;
  setpoint?: AnyConfig;
  soc?: AnyConfig;
  priceScatter?: AnyConfig;
  revenueByMode?: AnyConfig;
  energyByMode?: AnyConfig;
  durationByMode?: AnyConfig;
  issuers?: AnyConfig;

  // headline figures for the card subtitles
  totalRevenue = 0;
  bestDay: { date: string; revenue: number } | null = null;
  avgEventsPerDay = 0;
  chargeHours = '';
  dischargeHours = '';
  cheapestHour: number | null = null;
  dearestHour: number | null = null;

  /** Days covered by the dispatches shown; the step charts are easier to read when it is short. */
  spanDays = 0;

  shown(id: string): boolean {
    return !this.hidden.has(id);
  }

  ngOnChanges(): void {
    const a = this.analytics;
    if (!a || a.total === 0) {
      return;
    }
    // modes in the fixed stacking order, then any other mode present
    const present = new Set(a.modes.filter((m) => m.events > 0).map((m) => m.mode));
    const order = [...MODE_ORDER, ...a.modes.map((m) => m.mode).filter((m) => !MODE_ORDER.includes(m))];
    this.modeLegend = order
      .filter((m) => present.has(m))
      .map((m) => ({ code: m, label: modeLabel(m), color: this.modeColor(m) }));

    this.spanDays = a.days.length;
    this.buildDailyRevenue(a);
    this.buildCumulativeRevenue(a);
    this.buildEventsByMode(a, order);
    this.buildDailyEvents(a, order);
    this.buildModeHours(a, order);
    this.buildDailyEnergy(a);
    this.buildHourlyEnergy(a);
    this.buildHourlyPrice(a);
    this.buildSetpoint(a);
    this.buildSoc(a);
    this.buildPriceScatter(a, order);
    this.buildRevenueByMode(a, order);
    this.buildEnergyByMode(a, order);
    this.buildDurationByMode(a, order);
    this.buildIssuers(a);
  }

  modeColor(mode: string): string {
    return MODE_COLORS[mode] ?? INK;
  }

  formatDay(iso: string): string {
    return shortDate(iso);
  }

  usd(v: number): string {
    return usd(v);
  }

  hourLabel(hour: number): string {
    return `${String(hour).padStart(2, '0')}:00`;
  }

  // ---------------------------------------------------------------- the workbook's Summary charts

  private buildDailyRevenue(a: DispatchEventAnalytics): void {
    const days = a.days;
    this.totalRevenue = days.reduce((s, d) => s + d.revenue_usd, 0);
    const best = days.reduce((b, d, i) => (d.revenue_usd > days[b].revenue_usd ? i : b), 0);
    this.bestDay = days.length ? { date: days[best].date, revenue: days[best].revenue_usd } : null;
    this.dailyRevenue = {
      type: 'line',
      data: {
        labels: days.map((d) => shortDate(d.date)),
        datasets: [{
          label: 'Market revenue',
          data: days.map((d) => d.revenue_usd),
          borderColor: INK,
          backgroundColor: withAlpha(INK, 0.08),
          fill: 'origin',
          borderWidth: 2,
          tension: 0.25,
          pointRadius: 3,
          pointHoverRadius: 6,
          pointBackgroundColor: INK,
          pointBorderColor: SURFACE,
          pointBorderWidth: 1.5
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        onHover: pointerOnHover,
        onClick: (_e, elements) => {
          if (elements.length) {
            this.daySelect.emit(days[elements[0].index].date);
          }
        },
        scales: {
          x: categoryAxis(),
          y: valueAxis('USD per day', { beginAtZero: true, ticks: { color: INK_MUTED, font: { size: 11 }, callback: (v: number | string) => usd(Number(v)) } })
        },
        plugins: {
          legend: legend(false),
          tooltip: {
            ...tooltipBase(),
            callbacks: {
              label: (item: TooltipItem<'line'>) => ` Revenue ${usd(Number(item.raw), 2)}`,
              afterLabel: (item: TooltipItem<'line'>) => `${days[item.dataIndex].events} dispatches`,
              footer: () => 'Click to filter this day'
            }
          }
        }
      }
    } as AnyConfig;
  }

  private buildEventsByMode(a: DispatchEventAnalytics, order: string[]): void {
    const modes = order.map((m) => a.modes.find((x) => x.mode === m)).filter((m) => !!m && m.events > 0) as typeof a.modes;
    this.eventsByMode = {
      type: 'bar',
      data: {
        labels: modes.map((m) => modeLabel(m.mode)),
        datasets: [{
          label: 'Dispatch events',
          data: modes.map((m) => m.events),
          backgroundColor: modes.map((m) => this.modeColor(m.mode)),
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
            this.modeSelect.emit(modes[elements[0].index].mode);
          }
        },
        scales: {
          x: categoryAxis({ ticks: { color: INK_MUTED, font: { size: 11 }, maxRotation: 0, autoSkip: false } }),
          y: valueAxis(undefined, { beginAtZero: true, grace: '12%', ticks: { precision: 0, color: INK_MUTED, font: { size: 11 } } })
        },
        plugins: {
          legend: legend(false),
          valueLabels: { format: (v: number) => `${v}` },
          tooltip: {
            ...tooltipBase(),
            callbacks: {
              title: (items: TooltipItem<'bar'>[]) => (items.length ? modes[items[0].dataIndex].mode : ''),
              label: (item: TooltipItem<'bar'>) => ` ${item.raw} dispatches · ${Math.round((100 * Number(item.raw)) / a.total)}% of all`,
              afterLabel: (item: TooltipItem<'bar'>) => modes[item.dataIndex].description ?? '',
              footer: () => 'Click to filter by this mode'
            }
          }
        }
      }
    } as AnyConfig;
  }

  private buildDailyEvents(a: DispatchEventAnalytics, order: string[]): void {
    const days = a.days;
    this.avgEventsPerDay = days.length ? Math.round((10 * days.reduce((s, d) => s + d.events, 0)) / days.length) / 10 : 0;
    this.dailyEvents = {
      type: 'bar',
      data: {
        labels: days.map((d) => shortDate(d.date)),
        datasets: this.modeLegend.map((m) => ({
          label: m.label,
          data: days.map((d) => d.events_by_mode[m.code] ?? 0),
          backgroundColor: m.color,
          borderColor: SURFACE,
          borderWidth: { top: 2, bottom: 0, left: 0, right: 0 },
          borderSkipped: false,
          borderRadius: 2,
          maxBarThickness: 18
        }))
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        onHover: pointerOnHover,
        onClick: (_e, elements) => {
          if (elements.length) {
            this.daySelect.emit(days[elements[0].index].date);
          }
        },
        scales: {
          x: { ...categoryAxis(), stacked: true },
          y: { ...valueAxis('Dispatches', { beginAtZero: true, ticks: { precision: 0, color: INK_MUTED, font: { size: 11 } } }), stacked: true }
        },
        plugins: {
          legend: legend(false),
          tooltip: {
            ...tooltipBase(),
            filter: (item: TooltipItem<'bar'>) => Number(item.raw) > 0,
            callbacks: {
              title: (items: TooltipItem<'bar'>[]) => (items.length ? shortDate(days[items[0].dataIndex].date) : ''),
              footer: (items: TooltipItem<'bar'>[]) =>
                items.length ? `Total ${days[items[0].dataIndex].events} · click to filter this day` : ''
            }
          }
        }
      }
    } as AnyConfig;
  }

  // ---------------------------------------------------------------- time and energy

  private buildModeHours(a: DispatchEventAnalytics, _order: string[]): void {
    const days = a.days;
    this.modeHours = {
      type: 'bar',
      data: {
        labels: days.map((d) => shortDate(d.date)),
        datasets: this.modeLegend.map((m) => ({
          label: m.label,
          data: days.map((d) => Math.round(((d.minutes_by_mode[m.code] ?? 0) / 60) * 10) / 10),
          backgroundColor: m.color,
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
        scales: {
          x: { ...categoryAxis(), stacked: true },
          y: { ...valueAxis('Hours', { beginAtZero: true, max: 24, grace: 0, ticks: { stepSize: 6, color: INK_MUTED, font: { size: 11 } } }), stacked: true }
        },
        plugins: {
          legend: legend(false),
          tooltip: {
            ...tooltipBase(),
            filter: (item: TooltipItem<'bar'>) => Number(item.raw) > 0,
            callbacks: {
              title: (items: TooltipItem<'bar'>[]) => (items.length ? shortDate(days[items[0].dataIndex].date) : ''),
              label: (item: TooltipItem<'bar'>) => ` ${item.dataset.label}: ${minutesLabel(Number(item.raw) * 60)}`
            }
          }
        }
      }
    } as AnyConfig;
  }

  /** Charge above the axis, discharge below it; both in the same unit. */
  private diverging(labels: string[], charged: number[], discharged: number[], onClick?: (i: number) => void,
                    title?: (i: number) => string): AnyConfig {
    const bar = (label: string, data: number[], color: string) => ({
      label,
      data,
      backgroundColor: color,
      borderRadius: 3,
      borderSkipped: 'start' as const,
      maxBarThickness: 22
    });
    return {
      type: 'bar',
      data: {
        labels,
        datasets: [
          bar('Charged (import)', charged, CHARGE),
          bar('Discharged (export)', discharged.map((v) => -v), DISCHARGE)
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        onHover: onClick ? pointerOnHover : undefined,
        onClick: onClick
          ? (_e: ChartEvent, elements: ActiveElement[]) => {
              if (elements.length) {
                onClick(elements[0].index);
              }
            }
          : undefined,
        scales: {
          x: { ...categoryAxis(), stacked: true },
          y: {
            ...valueAxis('kWh (charge up, discharge down)'),
            stacked: true,
            ticks: { color: INK_MUTED, font: { size: 11 }, callback: (v: number | string) => Math.abs(Number(v)).toLocaleString() },
            grid: { color: (ctx: { tick: { value: number } }) => (ctx.tick.value === 0 ? '#9aa0a6' : GRID) }
          }
        },
        plugins: {
          legend: legend(true),
          tooltip: {
            ...tooltipBase(),
            callbacks: {
              title: (items: TooltipItem<'bar'>[]) => (items.length && title ? title(items[0].dataIndex) : items[0]?.label ?? ''),
              label: (item: TooltipItem<'bar'>) => ` ${item.dataset.label}: ${kwh(Number(item.raw))}`,
              footer: (items: TooltipItem<'bar'>[]) => {
                if (items.length < 2) {
                  return '';
                }
                const net = Number(items[0].raw) + Number(items[1].raw);
                return `Net ${net >= 0 ? '+' : '−'}${kwh(net)}${onClick ? ' · click to filter' : ''}`;
              }
            }
          }
        }
      }
    } as AnyConfig;
  }

  private buildDailyEnergy(a: DispatchEventAnalytics): void {
    const days = a.days;
    this.dailyEnergy = this.diverging(
      days.map((d) => shortDate(d.date)),
      days.map((d) => d.import_kwh),
      days.map((d) => d.export_kwh),
      (i) => this.daySelect.emit(days[i].date),
      (i) => shortDate(days[i].date)
    );
  }

  private buildHourlyEnergy(a: DispatchEventAnalytics): void {
    const hours = a.hours;
    const top = (key: 'import_kwh' | 'export_kwh') =>
      [...hours].sort((x, y) => y[key] - x[key]).filter((h) => h[key] > 0).slice(0, 2).map((h) => this.hourLabel(h.hour)).join(', ');
    this.chargeHours = top('import_kwh');
    this.dischargeHours = top('export_kwh');
    this.hourlyEnergy = this.diverging(
      hours.map((h) => String(h.hour).padStart(2, '0')),
      hours.map((h) => h.import_kwh),
      hours.map((h) => h.export_kwh),
      undefined,
      (i) => `${this.hourLabel(i)}–${this.hourLabel((i + 1) % 24)}`
    );
  }

  private buildHourlyPrice(a: DispatchEventAnalytics): void {
    const hours = a.hours;
    const priced = hours.filter((h) => h.avg_price_mwh !== null);
    this.cheapestHour = priced.length ? priced.reduce((b, h) => (h.avg_price_mwh! < b.avg_price_mwh! ? h : b)).hour : null;
    this.dearestHour = priced.length ? priced.reduce((b, h) => (h.avg_price_mwh! > b.avg_price_mwh! ? h : b)).hour : null;
    this.hourlyPrice = {
      type: 'bar',
      data: {
        labels: hours.map((h) => String(h.hour).padStart(2, '0')),
        datasets: [{
          label: 'Average price',
          data: hours.map((h) => h.avg_price_mwh),
          backgroundColor: INK,
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
          y: valueAxis('$/MWh', { beginAtZero: true })
        },
        plugins: {
          legend: legend(false),
          tooltip: {
            ...tooltipBase(),
            callbacks: {
              title: (items: TooltipItem<'bar'>[]) => (items.length ? `${this.hourLabel(items[0].dataIndex)}–${this.hourLabel((items[0].dataIndex + 1) % 24)}` : ''),
              label: (item: TooltipItem<'bar'>) => ` ${Number(item.raw).toFixed(2)} $/MWh (time-weighted)`
            }
          }
        }
      }
    } as AnyConfig;
  }

  // ---------------------------------------------------------------- over time

  private timeRange(points: DispatchPoint[]): { xMin: number; xMax: number } {
    const xs = points.map((p) => plantMs(p.effective_from));
    const ends = points.map((p) => (p.effective_to ? plantMs(p.effective_to) : plantMs(p.effective_from)));
    return { xMin: Math.min(...xs), xMax: Math.max(...ends, ...xs) };
  }

  private timeScale(xMin: number, xMax: number) {
    const axis = timeAxis(xMin, xMax);
    return { ...axis, ticks: { ...axis.ticks, color: INK_MUTED, font: { size: 11 } } };
  }

  private buildSetpoint(a: DispatchEventAnalytics): void {
    const pts = a.dispatches;
    if (!pts.length) {
      this.setpoint = undefined;
      return;
    }
    const { xMin, xMax } = this.timeRange(pts);
    // a step per dispatch: its setpoint holds from effective_from until the next one; the last one closes at its end
    const data: { x: number; y: number; d: DispatchPoint }[] = pts.map((p) => ({ x: plantMs(p.effective_from), y: p.p_setpoint_kw, d: p }));
    const last = pts[pts.length - 1];
    if (last.effective_to) {
      data.push({ x: plantMs(last.effective_to), y: last.p_setpoint_kw, d: last });
    }
    const modeAt = (ctx: ScriptableLineSegmentContext) => data[ctx.p0DataIndex]?.d.dispatch_mode ?? '';
    this.setpoint = {
      type: 'line',
      data: {
        datasets: [{
          label: 'Power setpoint',
          data,
          stepped: 'before',
          borderWidth: 1.5,
          pointRadius: 0,
          pointHitRadius: 6,
          pointHoverRadius: 4,
          fill: 'origin',
          segment: {
            borderColor: (ctx: ScriptableLineSegmentContext) => this.modeColor(modeAt(ctx)),
            backgroundColor: (ctx: ScriptableLineSegmentContext) => withAlpha(this.modeColor(modeAt(ctx)), 0.28)
          }
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        parsing: false,
        interaction: { mode: 'nearest', axis: 'x', intersect: false },
        onHover: pointerOnHover,
        onClick: (_e, elements) => {
          if (elements.length) {
            this.dispatchOpen.emit(data[elements[0].index].d.dispatch_id);
          }
        },
        scales: {
          x: this.timeScale(xMin, xMax),
          y: {
            ...valueAxis('kW (charge +, discharge −)'),
            grid: { color: (ctx: { tick: { value: number } }) => (ctx.tick.value === 0 ? '#9aa0a6' : GRID) }
          }
        },
        plugins: {
          legend: legend(false),
          tooltip: {
            ...tooltipBase(),
            callbacks: {
              title: (items: TooltipItem<'line'>[]) => {
                const d = (items[0]?.raw as { d: DispatchPoint })?.d;
                return d ? `${d.dispatch_id} · ${modeLabel(d.dispatch_mode)}` : '';
              },
              label: (item: TooltipItem<'line'>) => {
                const d = (item.raw as { d: DispatchPoint }).d;
                const p = d.p_setpoint_kw;
                return [
                  ` ${p > 0 ? 'Charge' : p < 0 ? 'Discharge' : 'Hold'} ${Math.abs(p).toLocaleString()} kW`,
                  ` ${formatFull(plantMs(d.effective_from))}${d.duration_min !== null ? ' · ' + minutesLabel(d.duration_min) : ' · running'}`
                ];
              },
              footer: () => 'Click to open the dispatch'
            }
          }
        }
      }
    } as AnyConfig;
  }

  private buildSoc(a: DispatchEventAnalytics): void {
    const pts = a.dispatches.filter((p) => p.soc_start_pct !== null || p.soc_end_pct !== null);
    if (!pts.length) {
      this.soc = undefined;
      return;
    }
    const { xMin, xMax } = this.timeRange(pts);
    // SOC at each dispatch's start and end; the line joins them in time order
    const socData: { x: number; y: number; d: DispatchPoint; at: string }[] = [];
    for (const p of pts) {
      if (p.soc_start_pct !== null) {
        socData.push({ x: plantMs(p.effective_from), y: p.soc_start_pct, d: p, at: 'start' });
      }
      if (p.soc_end_pct !== null && p.effective_to) {
        socData.push({ x: plantMs(p.effective_to), y: p.soc_end_pct, d: p, at: 'end' });
      }
    }
    const targetData = pts
      .filter((p) => p.target_soc_pct !== null)
      .map((p) => ({ x: plantMs(p.effective_from), y: p.target_soc_pct!, d: p, at: 'target' }));
    this.soc = {
      type: 'line',
      data: {
        datasets: [
          {
            label: 'SOC',
            data: socData,
            borderColor: INK,
            backgroundColor: INK,
            borderWidth: 2,
            pointRadius: 0,
            pointHitRadius: 6,
            pointHoverRadius: 4
          },
          {
            label: 'Target SOC',
            data: targetData,
            borderColor: INK_LIGHT,
            backgroundColor: INK_LIGHT,
            borderWidth: 1.5,
            borderDash: [5, 4],
            stepped: 'before',
            pointRadius: 0,
            pointHitRadius: 6,
            pointHoverRadius: 4
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        parsing: false,
        interaction: { mode: 'nearest', axis: 'x', intersect: false },
        scales: {
          x: this.timeScale(xMin, xMax),
          y: valueAxis('SOC (%)', { min: 0, max: 100, grace: 0, ticks: { stepSize: 20, color: INK_MUTED, font: { size: 11 } } })
        },
        plugins: {
          legend: legend(true),
          tooltip: {
            ...tooltipBase(),
            callbacks: {
              title: (items: TooltipItem<'line'>[]) => {
                const r = items[0]?.raw as { d: DispatchPoint };
                return r ? `${r.d.dispatch_id} · ${modeLabel(r.d.dispatch_mode)}` : '';
              },
              label: (item: TooltipItem<'line'>) => {
                const r = item.raw as { y: number; at: string; x: number };
                const what = r.at === 'target' ? 'Target' : r.at === 'start' ? 'SOC at start' : 'SOC at end';
                return ` ${what}: ${r.y.toFixed(1)} % · ${formatFull(r.x)}`;
              }
            }
          }
        }
      }
    } as AnyConfig;
  }

  private buildPriceScatter(a: DispatchEventAnalytics, _order: string[]): void {
    const byMode = this.modeLegend.map((m) => ({
      mode: m,
      points: a.dispatches.filter((p) => p.dispatch_mode === m.code && p.avg_price_mwh !== null)
    }));
    this.priceScatter = {
      type: 'scatter',
      data: {
        datasets: byMode.map(({ mode, points }) => ({
          label: mode.label,
          data: points.map((p) => ({ x: p.avg_price_mwh!, y: p.p_setpoint_kw, d: p })),
          backgroundColor: mode.color,
          borderColor: SURFACE,
          borderWidth: 1.5,
          pointRadius: 4.5,
          pointHoverRadius: 7,
          pointHitRadius: 8
        }))
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        onHover: pointerOnHover,
        onClick: (_e, elements) => {
          if (elements.length) {
            const el = elements[0];
            this.dispatchOpen.emit(byMode[el.datasetIndex].points[el.index].dispatch_id);
          }
        },
        scales: {
          x: valueAxis('Average price ($/MWh)', { grid: { color: GRID } }),
          y: {
            ...valueAxis('Setpoint kW (charge +, discharge −)'),
            grid: { color: (ctx: { tick: { value: number } }) => (ctx.tick.value === 0 ? '#9aa0a6' : GRID) }
          }
        },
        plugins: {
          legend: legend(false),
          tooltip: {
            ...tooltipBase(),
            callbacks: {
              title: (items: TooltipItem<'scatter'>[]) => {
                const d = (items[0]?.raw as { d: DispatchPoint })?.d;
                return d ? `${d.dispatch_id} · ${modeLabel(d.dispatch_mode)}` : '';
              },
              label: (item: TooltipItem<'scatter'>) => {
                const d = (item.raw as { d: DispatchPoint }).d;
                return [
                  ` ${d.p_setpoint_kw.toLocaleString()} kW at ${d.avg_price_mwh!.toFixed(2)} $/MWh`,
                  ` Revenue ${d.revenue_usd !== null ? usd(d.revenue_usd, 2) : '—'}`
                ];
              },
              footer: () => 'Click to open the dispatch'
            }
          }
        }
      }
    } as AnyConfig;
  }

  // ---------------------------------------------------------------- by mode / issuer

  private modeRows(a: DispatchEventAnalytics) {
    return this.modeLegend.map((m) => a.modes.find((x) => x.mode === m.code)!).filter(Boolean);
  }

  private horizontalBar(labels: string[], values: (number | null)[], colors: string | string[],
                        format: (v: number, i: number) => string, tooltip: Record<string, unknown>,
                        axisTitle?: string, axisTick?: (v: number) => string, labelRoom = '25%'): AnyConfig {
    return {
      type: 'bar',
      data: {
        labels,
        datasets: [{
          label: axisTitle ?? '',
          data: values,
          backgroundColor: colors,
          borderRadius: 4,
          borderSkipped: 'start',
          barPercentage: 0.8,
          categoryPercentage: 0.85,
          maxBarThickness: 20
        }]
      },
      options: {
        indexAxis: 'y',
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: {
            ...valueAxis(axisTitle, { grace: labelRoom }),
            ticks: { color: INK_MUTED, font: { size: 11 }, callback: (v: number | string) => (axisTick ? axisTick(Number(v)) : v) },
            grid: { color: (ctx: { tick: { value: number } }) => (ctx.tick.value === 0 ? '#9aa0a6' : GRID) }
          },
          y: { ...categoryAxis(), ticks: { color: INK_MUTED, font: { size: 11 }, autoSkip: false } }
        },
        plugins: {
          legend: legend(false),
          valueLabels: { format },
          tooltip: { ...tooltipBase(), callbacks: tooltip }
        }
      }
    } as AnyConfig;
  }

  private buildRevenueByMode(a: DispatchEventAnalytics, _order: string[]): void {
    const rows = this.modeRows(a);
    this.revenueByMode = this.horizontalBar(
      rows.map((r) => modeLabel(r.mode)),
      rows.map((r) => r.revenue_usd),
      rows.map((r) => this.modeColor(r.mode)),
      (v) => usd(v),
      {
        label: (item: TooltipItem<'bar'>) => ` ${usd(Number(item.raw), 2)} over ${rows[item.dataIndex].events} dispatches`,
        afterLabel: (item: TooltipItem<'bar'>) => (Number(item.raw) < 0 ? 'Cost of the energy bought' : 'Earned from energy sold')
      },
      'USD',
      (v) => usd(v)
    );
  }

  private buildEnergyByMode(a: DispatchEventAnalytics, _order: string[]): void {
    const rows = this.modeRows(a);
    const bar = (label: string, data: number[], color: string) => ({
      label,
      data,
      backgroundColor: color,
      borderRadius: 3,
      borderSkipped: 'start' as const,
      barPercentage: 0.8,
      categoryPercentage: 0.8,
      maxBarThickness: 14
    });
    this.energyByMode = {
      type: 'bar',
      data: {
        labels: rows.map((r) => modeLabel(r.mode)),
        datasets: [
          bar('Charged (import)', rows.map((r) => Math.round(r.import_kwh / 100) / 10), CHARGE),
          bar('Discharged (export)', rows.map((r) => Math.round(r.export_kwh / 100) / 10), DISCHARGE)
        ]
      },
      options: {
        indexAxis: 'y',
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: valueAxis('MWh', { beginAtZero: true, grace: '22%' }),
          y: { ...categoryAxis(), ticks: { color: INK_MUTED, font: { size: 11 }, autoSkip: false } }
        },
        plugins: {
          legend: legend(true),
          valueLabels: { format: (v: number) => `${v.toLocaleString()}` },
          tooltip: {
            ...tooltipBase(),
            callbacks: { label: (item: TooltipItem<'bar'>) => ` ${item.dataset.label}: ${Number(item.raw).toLocaleString()} MWh` }
          }
        }
      }
    } as AnyConfig;
  }

  private buildDurationByMode(a: DispatchEventAnalytics, _order: string[]): void {
    const rows = this.modeRows(a).filter((r) => r.mean_duration_min !== null);
    this.durationByMode = this.horizontalBar(
      rows.map((r) => modeLabel(r.mode)),
      rows.map((r) => r.mean_duration_min),
      rows.map((r) => this.modeColor(r.mode)),
      (v) => minutesLabel(v),
      {
        label: (item: TooltipItem<'bar'>) => ` Mean ${minutesLabel(Number(item.raw))}`,
        afterLabel: (item: TooltipItem<'bar'>) => {
          const r = rows[item.dataIndex];
          return [`Longest ${minutesLabel(r.max_duration_min)}`, `${Math.round(r.minutes / 60)} h in total`];
        }
      },
      'Mean minutes per dispatch',
      (v) => `${v}`,
      '30%'
    );
  }

  private buildIssuers(a: DispatchEventAnalytics): void {
    const src = a.sources;
    this.issuers = this.horizontalBar(
      src.map((s) => s.key),
      src.map((s) => s.count),
      INK,
      (v) => `${v}`,
      { label: (item: TooltipItem<'bar'>) => ` ${item.raw} dispatches · ${Math.round((100 * Number(item.raw)) / a.total)}% of all` },
      'Dispatches'
    );
  }

  private buildCumulativeRevenue(a: DispatchEventAnalytics): void {
    const days = a.days;
    let running = 0;
    const cumulative = days.map((d) => (running += d.revenue_usd));
    this.cumulativeRevenue = {
      type: 'line',
      data: {
        labels: days.map((d) => shortDate(d.date)),
        datasets: [{
          label: 'Cumulative revenue',
          data: cumulative.map((v) => Math.round(v * 100) / 100),
          borderColor: INK,
          backgroundColor: withAlpha(INK, 0.1),
          fill: 'origin',
          borderWidth: 2,
          pointRadius: days.length <= 3 ? 4 : 0,
          pointBackgroundColor: INK,
          pointHoverRadius: 5,
          tension: 0.2
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        scales: {
          x: categoryAxis(),
          y: valueAxis('USD', { beginAtZero: true, ticks: { color: INK_MUTED, font: { size: 11 }, callback: (v: number | string) => usd(Number(v)) } })
        },
        plugins: {
          legend: legend(false),
          tooltip: {
            ...tooltipBase(),
            callbacks: { label: (item: TooltipItem<'line'>) => ` ${usd(Number(item.raw), 2)} to date` }
          }
        }
      }
    } as AnyConfig;
  }
}
