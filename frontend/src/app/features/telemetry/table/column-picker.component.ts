import { Component, ElementRef, EventEmitter, HostListener, Input, OnInit, Output, inject } from '@angular/core';

import { TableColumn } from './table-column';

/**
 * "Columns" dropdown: a grouped checkbox list of every available column.
 * Starts from `defaultKeys`, remembers the choice under `storageKey`, and emits the
 * visible columns in table order whenever the selection changes (and once on init).
 */
@Component({
  selector: 'app-column-picker',
  standalone: true,
  templateUrl: './column-picker.component.html',
  styleUrl: './column-picker.component.scss'
})
export class ColumnPickerComponent implements OnInit {
  @Input({ required: true }) columns: TableColumn[] = [];
  @Input({ required: true }) defaultKeys: string[] = [];
  @Input({ required: true }) storageKey!: string;
  @Output() visibleChange = new EventEmitter<TableColumn[]>();

  private host = inject(ElementRef<HTMLElement>);

  open = false;
  selected = new Set<string>();
  groups: { name: string; columns: TableColumn[] }[] = [];
  visibleCount = 0;

  ngOnInit(): void {
    this.groups = [...new Set(this.columns.map((c) => c.group))].map((name) => ({
      name,
      columns: this.columns.filter((c) => c.group === name)
    }));
    this.selected = new Set(this.defaultKeys);
    try {
      const saved = JSON.parse(localStorage.getItem(this.storageKey) ?? 'null') as string[] | null;
      if (Array.isArray(saved)) {
        const known = new Set(this.columns.map((c) => c.key));
        this.selected = new Set(saved.filter((k) => known.has(k)));
      }
    } catch {
      // keep the default columns
    }
    // emit after the current change-detection pass so the parent can bind to it safely
    queueMicrotask(() => this.emit(false));
  }

  @HostListener('document:click', ['$event'])
  onDocumentClick(event: MouseEvent): void {
    if (this.open && !this.host.nativeElement.contains(event.target as Node)) {
      this.open = false;
    }
  }

  @HostListener('document:keydown.escape')
  onEscape(): void {
    this.open = false;
  }

  isSelected(column: TableColumn): boolean {
    return column.locked || this.selected.has(column.key);
  }

  toggle(column: TableColumn): void {
    if (column.locked) {
      return;
    }
    if (this.selected.has(column.key)) {
      this.selected.delete(column.key);
    } else {
      this.selected.add(column.key);
    }
    this.emit(true);
  }

  selectAll(): void {
    this.selected = new Set(this.columns.map((c) => c.key));
    this.emit(true);
  }

  reset(): void {
    this.selected = new Set(this.defaultKeys);
    this.emit(true);
  }

  get isDefault(): boolean {
    return this.selected.size === this.defaultKeys.length && this.defaultKeys.every((k) => this.selected.has(k));
  }

  private emit(save: boolean): void {
    const visible = this.columns.filter((c) => c.locked || this.selected.has(c.key));
    this.visibleCount = visible.length;
    this.visibleChange.emit(visible);
    if (save) {
      try {
        localStorage.setItem(this.storageKey, JSON.stringify([...this.selected]));
      } catch {
        // ignore write failures (e.g. private browsing)
      }
    }
  }
}
