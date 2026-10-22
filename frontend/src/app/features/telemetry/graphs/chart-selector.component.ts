import { Component, EventEmitter, Input, OnInit, Output } from '@angular/core';

export interface ChartOption {
  id: string;
  title: string;
  /** Short note under the title: what the chart plots. */
  meta: string;
}

/**
 * "Chart selector": checkbox cards to show or hide each chart of a graphical tab, with
 * Select all / Clear all. Same look as the selector on the BMS/PCS/EMS/HVAC graph pages.
 * Remembers the hidden charts under `storageKey`; emits them on init and on every change.
 */
@Component({
  selector: 'app-chart-selector',
  standalone: true,
  template: `
    <section class="chart-selector" aria-labelledby="chartSelectorTitle">
      <div class="chart-selector-head">
        <div>
          <h3 id="chartSelectorTitle">Chart selector</h3>
          <span class="chart-selector-count">{{ options.length - hidden.size }} of {{ options.length }} charts shown</span>
        </div>
        <div class="chart-selector-actions">
          <button type="button" class="btn btn-secondary btn-sm" [disabled]="hidden.size === 0" (click)="showAll()">Select all</button>
          <button type="button" class="btn btn-secondary btn-sm" [disabled]="hidden.size === options.length" (click)="hideAll()">
            Clear all
          </button>
        </div>
      </div>
      <div class="chart-selector-grid">
        @for (option of options; track option.id) {
          <label class="chart-option" [class.on]="!hidden.has(option.id)">
            <input type="checkbox" class="box" [checked]="!hidden.has(option.id)" (change)="toggle(option.id)" />
            <span class="chart-option-text">
              <span class="chart-option-title" [title]="option.title">{{ option.title }}</span>
              <span class="chart-option-meta" [title]="option.meta">{{ option.meta }}</span>
            </span>
          </label>
        }
      </div>
    </section>
  `,
  styleUrl: './chart-selector.scss'
})
export class ChartSelectorComponent implements OnInit {
  @Input({ required: true }) options: ChartOption[] = [];
  @Input({ required: true }) storageKey!: string;
  @Output() hiddenChange = new EventEmitter<Set<string>>();

  hidden = new Set<string>();

  ngOnInit(): void {
    try {
      const saved = JSON.parse(localStorage.getItem(this.storageKey) ?? 'null') as string[] | null;
      if (Array.isArray(saved)) {
        const known = new Set(this.options.map((o) => o.id));
        this.hidden = new Set(saved.filter((id) => known.has(id)));
      }
    } catch {
      // show every chart
    }
    // emit after the current change-detection pass so the parent can bind to it safely
    queueMicrotask(() => this.hiddenChange.emit(this.hidden));
  }

  toggle(id: string): void {
    const next = new Set(this.hidden);
    if (next.has(id)) {
      next.delete(id);
    } else {
      next.add(id);
    }
    this.update(next);
  }

  showAll(): void {
    this.update(new Set());
  }

  hideAll(): void {
    this.update(new Set(this.options.map((o) => o.id)));
  }

  private update(hidden: Set<string>): void {
    this.hidden = hidden;
    this.hiddenChange.emit(hidden);
    try {
      localStorage.setItem(this.storageKey, JSON.stringify([...hidden]));
    } catch {
      // ignore write failures (e.g. private browsing)
    }
  }
}
