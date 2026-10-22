import { CommonModule } from '@angular/common';
import { Component, EventEmitter, Input, Output } from '@angular/core';

export interface ReportField {
  label: string;
  value: string | null | undefined;
}

/**
 * The header of a PDF report: title, subtitle and the selected values (plant, battery system, unit, date ...).
 * Hidden on the page; shown only while the page is in report mode (`.report.pdf-mode`, see styles.scss), where it
 * replaces the filter dropdowns.
 */
@Component({
  selector: 'app-report-header',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="card report-header">
      <div class="report-title">
        <span class="report-kicker">BESS · Daily report</span>
        <h2>{{ title }}</h2>
        @if (subtitle) {
          <p class="subtitle">{{ subtitle }}</p>
        }
      </div>
      <dl class="report-meta">
        @for (f of fields; track f.label) {
          <div>
            <dt>{{ f.label }}</dt>
            <dd>{{ f.value || '—' }}</dd>
          </div>
        }
        <div>
          <dt>Generated</dt>
          <dd>{{ generatedAt | date: 'd MMM yyyy, HH:mm' }}</dd>
        </div>
      </dl>
    </div>
  `
})
export class ReportHeaderComponent {
  @Input({ required: true }) title = '';
  @Input() subtitle = '';
  @Input() fields: ReportField[] = [];
  @Input() generatedAt: Date = new Date();
}

/** The page-header "Download PDF" button. */
@Component({
  selector: 'app-pdf-button',
  standalone: true,
  template: `
    <button type="button" class="btn btn-primary" (click)="download.emit()" [disabled]="disabled || exporting"
      [title]="disabled ? 'Wait until the summary and charts have loaded' : 'Download this report as a PDF'">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path d="M12 4v11M7.5 10.5 12 15l4.5-4.5M5 19h14" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
      </svg>
      {{ exporting ? 'Preparing PDF…' + (progress ? ' ' + progress : '') : 'Download PDF' }}
    </button>
  `
})
export class PdfButtonComponent {
  @Input() disabled = false;
  @Input() exporting = false;
  /** Progress of a long report, e.g. "1/3". */
  @Input() progress = '';
  @Output() download = new EventEmitter<void>();
}
