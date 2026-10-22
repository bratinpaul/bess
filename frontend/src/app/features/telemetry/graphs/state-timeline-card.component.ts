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
import { Chart, ChartConfiguration, registerables } from 'chart.js';

import { StateSegment } from '../../../core/models/system-telemetry.model';
import { TimelineSpec, UNKNOWN_STATE_COLOR } from './chart-spec';
import { LEFT_AXIS_WIDTH, fixWidth, formatDuration, formatFull, rightAxis, timeAxis } from './time-axis';

Chart.register(...registerables);

export const NO_STATE = '(no value)';

type Bar = { x: [number, number]; y: string };

@Component({
  selector: 'app-state-timeline-card',
  standalone: true,
  templateUrl: './state-timeline-card.component.html',
  styleUrl: './telemetry-graphs.scss'
})
export class StateTimelineCardComponent implements AfterViewInit, OnChanges, OnDestroy {
  @Input({ required: true }) spec!: TimelineSpec;
  @Input() segments: StateSegment[] = [];
  /** Known states from the lookup table, used for ordering. */
  @Input() states: string[] = [];
  @Input() xMin = 0;
  @Input() xMax = 0;
  /** States to show; states not in this list are hidden. */
  @Input() selected: string[] = [];
  @Output() selectedChange = new EventEmitter<string[]>();

  @ViewChild('canvas') canvasRef?: ElementRef<HTMLCanvasElement>;

  presentStates: string[] = [];
  private totals: Record<string, string> = {};
  private chart?: Chart;

  ngAfterViewInit(): void {
    this.render();
  }

  ngOnChanges(): void {
    this.summarise();
    if (this.canvasRef) {
      this.render();
    }
  }

  ngOnDestroy(): void {
    this.chart?.destroy();
  }

  colorOf(state: string): string {
    return this.spec.colors[state] ?? UNKNOWN_STATE_COLOR;
  }

  isSelected(state: string): boolean {
    return this.selected.includes(state);
  }

  toggle(state: string): void {
    const next = this.isSelected(state) ? this.selected.filter((s) => s !== state) : [...this.selected, state];
    this.selectedChange.emit(next);
  }

  totalFor(state: string): string {
    return this.totals[state] ?? '';
  }

  /** Only states that occur in this range get a checkbox, in lookup-table order. */
  private summarise(): void {
    const ms: Record<string, number> = {};
    for (const s of this.segments) {
      const key = s.state ?? NO_STATE;
      ms[key] = (ms[key] ?? 0) + new Date(s.end).getTime() - new Date(s.start).getTime();
    }
    const known = this.states.filter((s) => s in ms);
    const unknown = Object.keys(ms).filter((s) => !this.states.includes(s));
    this.presentStates = [...known, ...unknown];
    this.totals = Object.fromEntries(Object.entries(ms).map(([k, v]) => [k, formatDuration(v)]));
  }

  private render(): void {
    if (!this.canvasRef) {
      return;
    }
    const lane = this.spec.laneLabel;
    const datasets = this.presentStates
      .filter((state) => this.isSelected(state))
      .map((state) => ({
        label: state,
        data: this.segments
          .filter((s) => (s.state ?? NO_STATE) === state)
          .map<Bar>((s) => ({ x: [new Date(s.start).getTime(), new Date(s.end).getTime()], y: lane })),
        backgroundColor: this.colorOf(state),
        borderWidth: 0,
        borderSkipped: false,
        grouped: false,
        barPercentage: 0.9,
        categoryPercentage: 1
      }));

    const config: ChartConfiguration<'bar', Bar[]> = {
      type: 'bar',
      data: { labels: [lane], datasets },
      options: {
        indexAxis: 'y',
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              title: (items) => (items.length ? String(items[0].dataset.label) : ''),
              label: (item) => {
                const [a, b] = (item.raw as Bar).x;
                return `${formatFull(a)} → ${formatFull(b)} (${formatDuration(b - a)})`;
              }
            }
          }
        },
        scales: {
          x: timeAxis(this.xMin, this.xMax),
          y: {
            afterFit: fixWidth(LEFT_AXIS_WIDTH),
            ticks: { display: false },
            grid: { display: false }
          },
          yRight: rightAxis(false, undefined)
        }
      }
    };
    this.chart?.destroy();
    this.chart = new Chart(this.canvasRef.nativeElement, config as unknown as ChartConfiguration);
  }
}
