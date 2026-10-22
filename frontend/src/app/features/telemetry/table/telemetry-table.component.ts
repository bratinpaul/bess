import { DatePipe } from '@angular/common';
import { Component, EventEmitter, Input, Output } from '@angular/core';

import { TableColumn, TableRow } from './table-column';

/** Scrollable telemetry table (both axes) with a sticky header row and sticky timestamp column; with `actions`,
 *  an edit / delete button pair at the end of each row. */
@Component({
  selector: 'app-telemetry-table',
  standalone: true,
  imports: [DatePipe],
  templateUrl: './telemetry-table.component.html'
})
export class TelemetryTableComponent {
  @Input({ required: true }) columns: TableColumn[] = [];
  @Input({ required: true }) rows: TableRow[] = [];
  /** Show edit / delete buttons per row (off by default). */
  @Input() actions = false;
  @Output() editRow = new EventEmitter<TableRow>();
  @Output() deleteRow = new EventEmitter<TableRow>();

  value(row: TableRow, column: TableColumn): unknown {
    return row[column.key];
  }
}
