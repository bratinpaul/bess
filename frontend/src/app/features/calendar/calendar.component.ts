import { CommonModule } from '@angular/common';
import { Component, ElementRef, OnInit, ViewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { BulkCalendarResult, CalendarDay, CalendarDayPage, DayType } from '../../core/models/calendar-day.model';
import { CalendarDayService } from '../../core/services/calendar-day.service';
import { ColumnPickerComponent } from '../telemetry/table/column-picker.component';
import { TableColumn, TableRow } from '../telemetry/table/table-column';
import { TelemetryTableComponent } from '../telemetry/table/telemetry-table.component';

const PAGE_SIZE_OPTIONS = [31, 62, 100];
const DAY_NAMES = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];

const CALENDAR_COLUMNS: TableColumn[] = [
  { key: 'calendar_date', label: 'Date', kind: 'text', group: 'Day', locked: true },
  { key: 'day_of_week', label: 'Day of Week', kind: 'text', group: 'Day' },
  { key: 'day_type', label: 'Day Type', kind: 'text', group: 'Day' },
  { key: 'weekend_label', label: 'Weekend', kind: 'text', group: 'Flags' },
  { key: 'holiday_label', label: 'Holiday', kind: 'text', group: 'Flags' },
  { key: 'holiday_name', label: 'Holiday Name', kind: 'text', group: 'Flags' }
];

interface EditState {
  mode: 'add' | 'edit';
  calendar_date: string;
  is_holiday: boolean;
  holiday_name: string;
}

/** Core -> Reference -> Calendar: the day-type calendar (weekday / weekend / holiday) used by load forecasting;
 *  upload, add / edit / delete days, tabular view. */
@Component({
  selector: 'app-calendar',
  standalone: true,
  imports: [CommonModule, FormsModule, ColumnPickerComponent, TelemetryTableComponent],
  templateUrl: './calendar.component.html',
  styleUrl: './calendar.component.scss'
})
export class CalendarComponent implements OnInit {
  @ViewChild('fileInput') fileInput?: ElementRef<HTMLInputElement>;

  // upload
  showUpload = false;
  selectedFile: File | null = null;
  uploading = false;
  uploadResult: BulkCalendarResult | null = null;
  uploadError: string | null = null;
  showAllUploadErrors = false;

  // table
  readonly allColumns = CALENDAR_COLUMNS;
  readonly defaultColumnKeys = CALENDAR_COLUMNS.map((c) => c.key);
  visibleColumns: TableColumn[] = CALENDAR_COLUMNS;
  page: CalendarDayPage | null = null;
  tableRows: TableRow[] = [];
  loading = true;
  error: string | null = null;
  filterStart = '';
  filterEnd = '';
  filterType: DayType | '' = '';
  filterHolidays = false;
  order: 'asc' | 'desc' = 'asc';
  readonly dayTypes: DayType[] = ['Weekday', 'Weekend', 'Holiday'];
  pageSizeOptions = PAGE_SIZE_OPTIONS;
  pageSize = PAGE_SIZE_OPTIONS[0];
  currentPage = 1;

  // add / edit / delete
  edit: EditState | null = null;
  saving = false;
  editError: string | null = null;
  toDelete: CalendarDay | null = null;
  deleting = false;
  deleteError: string | null = null;

  constructor(private service: CalendarDayService) {}

  ngOnInit(): void {
    this.fetchRows();
  }

  // ---------------------------------------------------------------- table

  get total(): number {
    return this.page?.total ?? 0;
  }

  get totalPages(): number {
    return Math.max(1, Math.ceil(this.total / this.pageSize));
  }

  get rangeStart(): number {
    return this.total === 0 ? 0 : (this.currentPage - 1) * this.pageSize + 1;
  }

  get rangeEnd(): number {
    return Math.min(this.currentPage * this.pageSize, this.total);
  }

  count(t: DayType): number {
    return this.page?.counts[t] ?? 0;
  }

  get daysInRange(): number {
    const c = this.page?.counts ?? {};
    return (c.Weekday ?? 0) + (c.Weekend ?? 0) + (c.Holiday ?? 0);
  }

  fetchRows(): void {
    this.loading = true;
    this.error = null;
    this.service
      .list({
        start: this.filterStart || undefined,
        end: this.filterEnd || undefined,
        dayType: this.filterType,
        holidaysOnly: this.filterHolidays,
        order: this.order,
        page: this.currentPage,
        pageSize: this.pageSize
      })
      .subscribe({
        next: (page) => {
          this.page = page;
          this.tableRows = page.items.map(
            (d) =>
              ({
                ...d,
                weekend_label: d.is_weekend ? 'Yes' : 'No',
                holiday_label: d.is_holiday ? 'Yes' : 'No',
                holiday_name: d.holiday_name ?? '—'
              }) as unknown as TableRow
          );
          this.loading = false;
        },
        error: () => {
          this.error = 'Could not load the calendar. Is the backend running?';
          this.loading = false;
        }
      });
  }

  applyFilters(): void {
    this.currentPage = 1;
    this.fetchRows();
  }

  clearFilters(): void {
    this.filterStart = '';
    this.filterEnd = '';
    this.filterType = '';
    this.filterHolidays = false;
    this.currentPage = 1;
    this.fetchRows();
  }

  toggleOrder(): void {
    this.order = this.order === 'asc' ? 'desc' : 'asc';
    this.currentPage = 1;
    this.fetchRows();
  }

  setPageSize(size: number): void {
    this.pageSize = size;
    this.currentPage = 1;
    this.fetchRows();
  }

  goToPage(page: number): void {
    if (page >= 1 && page <= this.totalPages) {
      this.currentPage = page;
      this.fetchRows();
    }
  }

  // ---------------------------------------------------------------- upload

  get visibleUploadErrors() {
    if (!this.uploadResult) {
      return [];
    }
    return this.showAllUploadErrors ? this.uploadResult.errors : this.uploadResult.errors.slice(0, 10);
  }

  onFileSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    this.selectedFile = input.files && input.files.length > 0 ? input.files[0] : null;
    this.uploadResult = null;
    this.uploadError = null;
    this.showAllUploadErrors = false;
  }

  upload(): void {
    if (!this.selectedFile) {
      return;
    }
    this.uploading = true;
    this.uploadError = null;
    this.uploadResult = null;
    this.service.bulkUpload(this.selectedFile).subscribe({
      next: (result) => {
        this.uploadResult = result;
        this.uploading = false;
        this.selectedFile = null;
        if (this.fileInput) {
          this.fileInput.nativeElement.value = '';
        }
        this.currentPage = 1;
        this.fetchRows();
      },
      error: (err) => {
        this.uploadError = err?.error?.detail || 'Upload failed. Is the backend running?';
        this.uploading = false;
      }
    });
  }

  // ---------------------------------------------------------------- add / edit / delete

  /** What the date and holiday flag make of the day (shown read-only in the form). */
  get derived(): { dow: string; weekend: boolean; type: DayType } | null {
    const e = this.edit;
    if (!e || !/^\d{4}-\d{2}-\d{2}$/.test(e.calendar_date)) {
      return null;
    }
    const [y, m, d] = e.calendar_date.split('-').map(Number);
    const dowIdx = new Date(Date.UTC(y, m - 1, d)).getUTCDay();
    const weekend = dowIdx === 0 || dowIdx === 6;
    return { dow: DAY_NAMES[dowIdx], weekend, type: e.is_holiday ? 'Holiday' : weekend ? 'Weekend' : 'Weekday' };
  }

  openAdd(): void {
    const last = this.page?.last_date;
    let next = new Date().toISOString().slice(0, 10);
    if (last) {
      const d = new Date(last + 'T00:00:00Z');
      d.setUTCDate(d.getUTCDate() + 1);
      next = d.toISOString().slice(0, 10);
    }
    this.editError = null;
    this.edit = { mode: 'add', calendar_date: next, is_holiday: false, holiday_name: '' };
  }

  openEdit(row: TableRow): void {
    const r = row as unknown as CalendarDay;
    this.editError = null;
    this.edit = {
      mode: 'edit',
      calendar_date: r.calendar_date,
      is_holiday: r.is_holiday,
      holiday_name: r.is_holiday && r.holiday_name && r.holiday_name !== '—' ? r.holiday_name : ''
    };
  }

  get editProblem(): string | null {
    const e = this.edit;
    if (!e) {
      return null;
    }
    if (!this.derived) {
      return 'Enter the date';
    }
    if (e.is_holiday && !e.holiday_name.trim()) {
      return 'Name the holiday';
    }
    return null;
  }

  save(): void {
    const e = this.edit;
    if (!e || this.editProblem) {
      return;
    }
    const body = { is_holiday: e.is_holiday, holiday_name: e.is_holiday ? e.holiday_name.trim() : null };
    this.saving = true;
    this.editError = null;
    const req$ =
      e.mode === 'add'
        ? this.service.add({ ...body, calendar_date: e.calendar_date })
        : this.service.update(e.calendar_date, body);
    req$.subscribe({
      next: () => {
        this.saving = false;
        this.edit = null;
        this.fetchRows();
      },
      error: (err) => {
        this.saving = false;
        const d = err?.error?.detail;
        this.editError = Array.isArray(d) ? d.map((x: { msg: string }) => x.msg.replace(/^Value error, /, '')).join('; ') : d || 'Saving failed.';
      }
    });
  }

  confirmDelete(row: TableRow): void {
    this.deleteError = null;
    this.toDelete = row as unknown as CalendarDay;
  }

  deleteConfirmed(): void {
    const t = this.toDelete;
    if (!t) {
      return;
    }
    this.deleting = true;
    this.service.delete(t.calendar_date).subscribe({
      next: () => {
        this.deleting = false;
        this.toDelete = null;
        this.fetchRows();
      },
      error: (err) => {
        this.deleting = false;
        this.deleteError = err?.error?.detail || 'Deleting failed.';
      }
    });
  }
}
