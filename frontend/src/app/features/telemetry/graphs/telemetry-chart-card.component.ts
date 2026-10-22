import {
  AfterViewInit,
  Component,
  ElementRef,
  EventEmitter,
  Input,
  OnChanges,
  OnDestroy,
  Output,
  ViewChild
} from '@angular/core';
import { Chart, ChartConfiguration, ChartDataset, registerables } from 'chart.js';

import { AxisRange, ChartSpec, CounterSpec, RefLine, SeriesPoint } from './chart-spec';
import { LEFT_AXIS_WIDTH, fixWidth, formatFull, rightAxis, timeAxis } from './time-axis';

Chart.register(...registerables);

type Point = { x: number; y: number | null };
type Dataset = ChartDataset<'line' | 'bar', Point[]> & { isRef?: boolean };

function withAlpha(hex: string, alpha: number): string {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
}

function toNumber(value: number | string | null | undefined): number | null {
  if (value === null || value === undefined || value === '') {
    return null;
  }
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

@Component({
  selector: 'app-telemetry-chart-card',
  standalone: true,
  templateUrl: './telemetry-chart-card.component.html',
  styleUrl: './telemetry-graphs.scss'
})
export class TelemetryChartCardComponent implements AfterViewInit, OnChanges, OnDestroy {
  @Input({ required: true }) spec!: ChartSpec;
  @Input() points: SeriesPoint[] = [];
  @Input() refs: Record<string, number | null> = {};
  @Input() xMin = 0;
  @Input() xMax = 0;
  @Input() selected: string[] = [];
  @Output() selectedChange = new EventEmitter<string[]>();

  @ViewChild('canvas') canvasRef?: ElementRef<HTMLCanvasElement>;

  private chart?: Chart;

  ngAfterViewInit(): void {
    this.render();
  }

  ngOnChanges(): void {
    if (this.canvasRef) {
      this.render();
    }
  }

  ngOnDestroy(): void {
    this.chart?.destroy();
  }

  isSelected(counter: CounterSpec): boolean {
    return this.selected.includes(counter.key);
  }

  toggle(counter: CounterSpec): void {
    const next = this.isSelected(counter)
      ? this.selected.filter((k) => k !== counter.key)
      : [...this.selected, counter.key];
    this.selectedChange.emit(next);
  }

  get hasSelection(): boolean {
    return this.spec.counters.some((c) => this.isSelected(c));
  }

  get usesRightAxis(): boolean {
    return this.spec.counters.some((c) => c.axis === 'y2' && this.isSelected(c));
  }

  /** Reference lines that resolve to a value for the current series. */
  get activeRefLines(): { line: RefLine; value: number }[] {
    return (this.spec.refLines ?? [])
      .map((line) => {
        const base = line.value ?? (line.ref ? this.refs[line.ref] : null);
        return { line, value: base === null || base === undefined ? NaN : base * (line.scale ?? 1) };
      })
      .filter((r) => Number.isFinite(r.value));
  }

  private series(counter: CounterSpec): Point[] {
    const sign = counter.negate ? -1 : 1;
    return this.points.map((p) => {
      const v = toNumber(p[counter.key]);
      return { x: new Date(p.ts).getTime(), y: v === null ? null : sign * v };
    });
  }

  private flatLine(value: number): Point[] {
    return [
      { x: this.xMin, y: value },
      { x: this.xMax, y: value }
    ];
  }

  private buildDatasets(): Dataset[] {
    const datasets: Dataset[] = [];
    const band = this.spec.refBand;
    if (band) {
      // reference band: a transparent lower edge, then an upper edge filled down to it
      const lower = datasets.length;
      datasets.push(this.refDataset(band.label, this.flatLine(band.from), 'transparent', 0));
      datasets.push({
        ...this.refDataset(band.label, this.flatLine(band.to), 'transparent', 0),
        fill: { target: lower },
        backgroundColor: withAlpha(band.color, 0.1)
      } as Dataset);
    }

    const active = this.spec.counters.filter((c) => this.isSelected(c));
    const min = active.find((c) => c.role === 'bandMin');
    const max = active.find((c) => c.role === 'bandMax');
    if (min) {
      datasets.push(this.lineDataset(min, { borderWidth: 1, borderDash: [4, 3] }));
    }
    if (max) {
      datasets.push(
        this.lineDataset(max, {
          borderWidth: 1,
          borderDash: [4, 3],
          // absolute index of the min edge pushed just before, when it is shown
          fill: min ? { target: datasets.length - 1 } : false,
          backgroundColor: withAlpha(max.color, 0.14)
        })
      );
    }
    for (const c of active) {
      if (c === min || c === max) {
        continue;
      }
      if (c.role === 'bar') {
        datasets.push({
          type: 'bar',
          label: c.label,
          data: this.series(c),
          yAxisID: c.axis ?? 'y',
          backgroundColor: c.negativeColor
            ? (ctx: { raw?: unknown }) =>
                withAlpha(((ctx.raw as Point | undefined)?.y ?? 0) < 0 ? c.negativeColor! : c.color, 0.6)
            : withAlpha(c.color, 0.55),
          borderWidth: 0,
          barPercentage: 1,
          categoryPercentage: 1
        } as Dataset);
      } else if (c.role === 'area') {
        datasets.push(
          this.lineDataset(c, {
            borderWidth: 1,
            borderColor: withAlpha(c.color, 0.6),
            fill: 'origin',
            backgroundColor: withAlpha(c.color, 0.12),
            tension: 0
          })
        );
      } else {
        datasets.push(
          this.lineDataset(c, {
            borderWidth: c.dashed ? 1.6 : 2,
            ...(c.dashed ? { borderDash: [6, 4] } : {}),
            ...(c.stepped ? { stepped: 'after', tension: 0 } : {})
          })
        );
      }
    }

    for (const { line, value } of this.activeRefLines) {
      datasets.push({
        ...this.refDataset(line.label, this.flatLine(value), line.color, 1.2),
        yAxisID: line.axis ?? 'y'
      } as Dataset);
    }
    return datasets;
  }

  private refDataset(label: string, data: Point[], color: string, width: number): Dataset {
    return {
      type: 'line',
      label,
      data,
      isRef: true,
      borderColor: color,
      borderWidth: width,
      borderDash: [6, 4],
      pointRadius: 0,
      pointHitRadius: 0,
      fill: false,
      order: 10
    } as Dataset;
  }

  private lineDataset(c: CounterSpec, extra: Record<string, unknown>): Dataset {
    return {
      type: 'line',
      label: c.label,
      data: this.series(c),
      yAxisID: c.axis ?? 'y',
      borderColor: c.color,
      backgroundColor: c.color,
      pointRadius: 0,
      pointHitRadius: 4,
      tension: 0.1,
      spanGaps: false,
      ...extra
    } as Dataset;
  }

  private axisRange(range: AxisRange | undefined, axis: 'y' | 'y2') {
    if (!range) {
      return {};
    }
    const { stepSize, fitToData, ...limits } = range;
    const out: Record<string, unknown> = { ...limits };
    if (stepSize) {
      // decimals of the step, so 0.05 renders as 49.85 rather than 49.849999
      const decimals = (String(stepSize).split('.')[1] ?? '').length;
      out['ticks'] = { stepSize, callback: (v: string | number) => Number(v).toFixed(decimals) };
    }
    if (fitToData && stepSize) {
      const values = this.spec.counters
        .filter((c) => (c.axis ?? 'y') === axis && this.isSelected(c))
        .flatMap((c) => this.series(c).map((p) => p.y))
        .filter((v): v is number => v !== null);
      if (values.length) {
        const round = (v: number) => Number(v.toFixed(6));
        out['min'] = round((Math.floor(Math.min(...values) / stepSize) - 1) * stepSize);
        out['max'] = round((Math.ceil(Math.max(...values) / stepSize) + 1) * stepSize);
        delete out['suggestedMin'];
        delete out['suggestedMax'];
      }
    }
    return out;
  }

  private render(): void {
    if (!this.canvasRef) {
      return;
    }
    const datasets = this.buildDatasets();
    const showRight = this.usesRightAxis;
    const config: ChartConfiguration<'line' | 'bar', Point[]> = {
      type: 'line',
      data: { datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        normalized: true,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { display: false },
          tooltip: {
            filter: (item) => !(item.dataset as Dataset).isRef,
            callbacks: {
              title: (items) => (items.length ? formatFull(items[0].parsed.x as number) : '')
            }
          }
        },
        scales: {
          x: timeAxis(this.xMin, this.xMax),
          y: {
            position: 'left',
            title: { display: true, text: this.spec.yLabel },
            afterFit: fixWidth(LEFT_AXIS_WIDTH),
            grid: { color: 'rgba(0,0,0,0.05)' },
            ...this.axisRange(this.spec.y, 'y')
          },
          y2: { ...rightAxis(showRight, this.spec.y2Label), ...this.axisRange(this.spec.y2, 'y2') }
        }
      }
    };
    this.chart?.destroy();
    this.chart = new Chart(this.canvasRef.nativeElement, config as ChartConfiguration);
  }
}
