import { AfterViewInit, Component, ElementRef, Input, OnChanges, OnDestroy, ViewChild } from '@angular/core';
import { Chart, ChartConfiguration, Plugin, registerables } from 'chart.js';

Chart.register(...registerables);

const LABEL_INK = '#52565c';

/**
 * Draws each bar's value just past its end, when a config sets
 * `options.plugins.valueLabels = { format: (value, index) => string }` (non-stacked bar charts).
 * Not declared on Chart.js's types on purpose: augmenting them breaks other pages' typed Chart fields.
 */
const valueLabelsPlugin: Plugin<'bar'> = {
  id: 'valueLabels',
  afterDatasetsDraw(chart, _args, options: { format?: (value: number, index: number) => string }) {
    if (!options?.format) {
      return;
    }
    const { ctx } = chart;
    const horizontal = chart.options.indexAxis === 'y';
    ctx.save();
    ctx.font = '600 11px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';
    ctx.fillStyle = LABEL_INK;
    chart.data.datasets.forEach((dataset, di) => {
      const meta = chart.getDatasetMeta(di);
      if (meta.hidden) {
        return;
      }
      meta.data.forEach((bar, i) => {
        const value = Number(dataset.data[i]);
        if (!Number.isFinite(value) || value === 0) {
          return;
        }
        const { x, y } = bar.getProps(['x', 'y'], true);
        const text = options.format!(value, i);
        // past the bar's end: right of / above a positive bar, left of / below a negative one
        if (horizontal) {
          ctx.textAlign = value < 0 ? 'right' : 'left';
          ctx.textBaseline = 'middle';
          ctx.fillText(text, value < 0 ? x - 6 : x + 6, y);
        } else {
          ctx.textAlign = 'center';
          ctx.textBaseline = value < 0 ? 'top' : 'bottom';
          ctx.fillText(text, x, value < 0 ? y + 4 : y - 4);
        }
      });
    });
    ctx.restore();
  }
};

/** A Chart.js canvas; the chart is rebuilt whenever `config` changes. */
@Component({
  selector: 'app-chart-canvas',
  standalone: true,
  template: `<div class="chart-canvas-box" [style.height.px]="height"><canvas #canvas></canvas></div>`,
  styles: [`.chart-canvas-box { position: relative; }`]
})
export class ChartCanvasComponent implements AfterViewInit, OnChanges, OnDestroy {
  @Input({ required: true }) config!: ChartConfiguration;
  @Input() height = 260;

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

  private render(): void {
    this.chart?.destroy();
    if (!this.canvasRef || !this.config) {
      return;
    }
    this.chart = new Chart(this.canvasRef.nativeElement, {
      ...this.config,
      plugins: [...(this.config.plugins ?? []), valueLabelsPlugin as Plugin]
    });
  }
}
