import { Component, Input, OnChanges, OnInit, SimpleChanges } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { ChartSpec, GraphEntity, GraphSeries, SeriesLoader, TimelineSpec } from './chart-spec';
import { StateTimelineCardComponent } from './state-timeline-card.component';
import { TelemetryChartCardComponent } from './telemetry-chart-card.component';
import { formatDuration, formatFull } from './time-axis';

interface GraphPrefs {
  hidden: string[];
  selected: Record<string, string[]>;
}

/** 'yyyy-MM-ddTHH:mm' in local time, the format a datetime-local input expects. */
function toLocalInput(iso: string | null): string {
  if (!iso) {
    return '';
  }
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/**
 * Graphical telemetry view: entity + time-range filters, a chart selector, and a stack of
 * time-aligned charts and state timelines. Each telemetry page supplies its own chart
 * definitions and a loader for its series endpoint.
 */
@Component({
  selector: 'app-telemetry-graphs',
  standalone: true,
  imports: [FormsModule, TelemetryChartCardComponent, StateTimelineCardComponent],
  templateUrl: './telemetry-graphs.component.html',
  styleUrl: './telemetry-graphs.scss'
})
export class TelemetryGraphsComponent implements OnInit, OnChanges {
  @Input({ required: true }) charts: ChartSpec[] = [];
  @Input() timelines: TimelineSpec[] = [];
  @Input({ required: true }) loader!: SeriesLoader;
  /** localStorage key for the chart selector and counter selections. */
  @Input({ required: true }) prefsKey!: string;
  @Input() entities: GraphEntity[] = [];
  @Input() entityLabel = 'System';
  /** Seed values carried over from the tabular filters. */
  @Input() initialEntityId = '';
  @Input() initialStart = '';
  @Input() initialEnd = '';

  entityId = '';
  start = '';
  end = '';

  series: GraphSeries | null = null;
  loading = false;
  error: string | null = null;

  hidden = new Set<string>();
  selected: Record<string, string[]> = {};
  summaries: Record<string, string> = {};

  ngOnInit(): void {
    this.loadPrefs();
    // stable arrays per chart, so the chart cards only redraw when a selection really changes
    for (const chart of this.charts) {
      this.selected[chart.id] ??= chart.counters.map((c) => c.key);
      this.summaries[chart.id] = chart.counters.map((c) => c.label).join(' · ');
    }
    this.entityId = this.initialEntityId || this.entities[0]?.id || '';
    this.start = this.initialStart;
    this.end = this.initialEnd;
    if (this.entityId) {
      this.load();
    }
  }

  ngOnChanges(changes: SimpleChanges): void {
    // the entity list may arrive after init; pick the first one if nothing is chosen yet
    if (changes['entities'] && !changes['entities'].firstChange && !this.entityId && this.entities.length) {
      this.entityId = this.entities[0].id;
      this.load();
    }
  }

  get totalCharts(): number {
    return this.charts.length + this.timelines.length;
  }

  get shownCount(): number {
    return this.visibleCharts.length + this.visibleTimelines.length;
  }

  get xMin(): number {
    return this.series?.start ? new Date(this.series.start).getTime() : 0;
  }

  get xMax(): number {
    return this.series?.end ? new Date(this.series.end).getTime() : 0;
  }

  get visibleCharts(): ChartSpec[] {
    return this.charts.filter((c) => !this.hidden.has(c.id));
  }

  get visibleTimelines(): TimelineSpec[] {
    return this.timelines.filter((t) => !this.hidden.has(t.id));
  }

  get rangeLabel(): string {
    if (!this.series?.start || !this.series.end) {
      return '';
    }
    return `${formatFull(this.xMin)} → ${formatFull(this.xMax)}`;
  }

  get resolutionLabel(): string {
    if (!this.series) {
      return '';
    }
    const bucket = formatDuration(this.series.bucketSeconds * 1000);
    const raw = this.series.rawIntervalSeconds;
    if (raw && raw >= this.series.bucketSeconds) {
      return `raw ${bucket} readings`;
    }
    return `${bucket} averages (min/max kept for bands)`;
  }

  load(): void {
    if (!this.entityId) {
      this.error = `Select a ${this.entityLabel}.`;
      return;
    }
    if (this.start && this.end && this.start > this.end) {
      this.error = '"From" must be before "To".';
      return;
    }
    this.loading = true;
    this.error = null;
    this.loader(this.entityId, this.start || undefined, this.end || undefined).subscribe({
      next: (series) => {
        // every declared timeline gets an entry, so template bindings stay stable references
        for (const t of this.timelines) {
          series.timelines[t.id] ??= { states: [], segments: [] };
        }
        this.series = series;
        this.loading = false;
        // show the window the API actually used (it defaults to the last 7 days of data)
        this.start = toLocalInput(series.start);
        this.end = toLocalInput(series.end);
        for (const t of this.timelines) {
          if (!this.selected[t.id]) {
            const timeline = series.timelines[t.id];
            const seen = (timeline?.segments ?? []).map((s) => s.state ?? '(no value)');
            this.selected[t.id] = [...new Set([...(timeline?.states ?? []), ...seen])];
          }
        }
      },
      error: (err) => {
        this.error = err?.error?.detail || 'Could not load telemetry series. Is the backend running?';
        this.loading = false;
      }
    });
  }

  resetRange(): void {
    this.start = '';
    this.end = '';
    this.load();
  }

  setSelected(id: string, keys: string[]): void {
    this.selected = { ...this.selected, [id]: keys };
    this.savePrefs();
  }

  isShown(id: string): boolean {
    return !this.hidden.has(id);
  }

  toggleChart(id: string): void {
    if (this.hidden.has(id)) {
      this.hidden.delete(id);
    } else {
      this.hidden.add(id);
    }
    this.hidden = new Set(this.hidden);
    this.savePrefs();
  }

  hideAllCharts(): void {
    this.hidden = new Set([...this.charts.map((c) => c.id), ...this.timelines.map((t) => t.id)]);
    this.savePrefs();
  }

  showAllCharts(): void {
    this.hidden = new Set();
    this.savePrefs();
  }

  private loadPrefs(): void {
    try {
      const prefs = JSON.parse(localStorage.getItem(this.prefsKey) ?? 'null') as GraphPrefs | null;
      if (prefs) {
        this.hidden = new Set(prefs.hidden ?? []);
        this.selected = prefs.selected ?? {};
      }
    } catch {
      // keep defaults
    }
  }

  private savePrefs(): void {
    try {
      const prefs: GraphPrefs = { hidden: [...this.hidden], selected: this.selected };
      localStorage.setItem(this.prefsKey, JSON.stringify(prefs));
    } catch {
      // ignore write failures (e.g. private browsing)
    }
  }
}
