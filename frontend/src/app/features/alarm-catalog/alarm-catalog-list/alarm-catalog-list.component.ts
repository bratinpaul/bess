import { CommonModule } from '@angular/common';
import { Component, ElementRef, OnInit, ViewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';

import {
  ALARM_SOURCES,
  AlarmCatalogEntry,
  AlarmSeverity,
  BulkAlarmCatalogResult
} from '../../../core/models/alarm-catalog.model';
import { AlarmCatalogService } from '../../../core/services/alarm-catalog.service';

type SortColumn = 'source' | 'alarm_code' | 'alarm_type' | 'severity_level' | 'asset_type';
type SortDirection = 'asc' | 'desc';

const PAGE_SIZE_OPTIONS = [10, 25, 50];

@Component({
  selector: 'app-alarm-catalog-list',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  templateUrl: './alarm-catalog-list.component.html',
  styleUrl: './alarm-catalog-list.component.scss'
})
export class AlarmCatalogListComponent implements OnInit {
  @ViewChild('fileInput') fileInput?: ElementRef<HTMLInputElement>;

  items: AlarmCatalogEntry[] = [];
  severities: AlarmSeverity[] = [];
  sources = ALARM_SOURCES;
  loading = true;
  error: string | null = null;

  itemToDelete: AlarmCatalogEntry | null = null;
  deleting = false;
  deleteError: string | null = null;

  // filters
  searchTerm = '';
  sourceFilter = '';
  severityFilter: number | null = null;
  sortColumn: SortColumn = 'source';
  sortDirection: SortDirection = 'asc';

  pageSizeOptions = PAGE_SIZE_OPTIONS;
  pageSize = PAGE_SIZE_OPTIONS[1];
  currentPage = 1;

  // bulk load
  selectedFile: File | null = null;
  uploading = false;
  uploadResult: BulkAlarmCatalogResult | null = null;
  uploadError: string | null = null;
  showAllUploadErrors = false;

  constructor(
    private service: AlarmCatalogService,
    private router: Router
  ) {}

  ngOnInit(): void {
    this.service.lookups().subscribe({
      next: (lookups) => (this.severities = lookups.severities),
      error: () => {
        /* the severity filter is optional */
      }
    });
    this.fetchData();
  }

  fetchData(): void {
    this.loading = true;
    this.error = null;
    this.service.list().subscribe({
      next: (items) => {
        this.items = items;
        this.loading = false;
      },
      error: () => {
        this.error = 'Could not load the alarm catalog. Is the backend running?';
        this.loading = false;
      }
    });
  }

  countBy(source: string): number {
    return this.items.filter((i) => i.source === source).length;
  }

  // ---------------------------------------------------------------- table

  get filteredItems(): AlarmCatalogEntry[] {
    const term = this.searchTerm.trim().toLowerCase();
    return this.items.filter(
      (item) =>
        (!this.sourceFilter || item.source === this.sourceFilter) &&
        (this.severityFilter === null || item.severity_level === this.severityFilter) &&
        (!term ||
          [item.alarm_code, item.alarm_type, item.asset_type, item.description, item.probable_cause, item.unit]
            .filter((v): v is string => !!v)
            .some((v) => v.toLowerCase().includes(term)))
    );
  }

  get sortedItems(): AlarmCatalogEntry[] {
    const column = this.sortColumn;
    const direction = this.sortDirection === 'asc' ? 1 : -1;
    return [...this.filteredItems].sort((a, b) => {
      const aValue = a[column];
      const bValue = b[column];
      if (aValue === null || aValue === undefined) return 1;
      if (bValue === null || bValue === undefined) return -1;
      const primary =
        typeof aValue === 'number' && typeof bValue === 'number'
          ? aValue - bValue
          : String(aValue).localeCompare(String(bValue), undefined, { numeric: true, sensitivity: 'base' });
      // within a source / severity / type, keep the codes in order
      return (primary || a.alarm_code.localeCompare(b.alarm_code)) * direction;
    });
  }

  get totalItems(): number {
    return this.filteredItems.length;
  }

  get totalPages(): number {
    return Math.max(1, Math.ceil(this.totalItems / this.pageSize));
  }

  get pagedItems(): AlarmCatalogEntry[] {
    const page = Math.min(this.currentPage, this.totalPages);
    const start = (page - 1) * this.pageSize;
    return this.sortedItems.slice(start, start + this.pageSize);
  }

  get rangeStart(): number {
    return this.totalItems === 0 ? 0 : (this.currentPage - 1) * this.pageSize + 1;
  }

  get rangeEnd(): number {
    return Math.min(this.currentPage * this.pageSize, this.totalItems);
  }

  get hasFilters(): boolean {
    return !!this.searchTerm.trim() || !!this.sourceFilter || this.severityFilter !== null;
  }

  onFilterChange(): void {
    this.currentPage = 1;
  }

  clearFilters(): void {
    this.searchTerm = '';
    this.sourceFilter = '';
    this.severityFilter = null;
    this.currentPage = 1;
  }

  setSort(column: SortColumn): void {
    if (this.sortColumn === column) {
      this.sortDirection = this.sortDirection === 'asc' ? 'desc' : 'asc';
    } else {
      this.sortColumn = column;
      this.sortDirection = 'asc';
    }
  }

  setPageSize(size: number): void {
    this.pageSize = size;
    this.currentPage = 1;
  }

  goToPage(page: number): void {
    if (page >= 1 && page <= this.totalPages) {
      this.currentPage = page;
    }
  }

  view(item: AlarmCatalogEntry): void {
    this.router.navigate(['/alarm-catalog', item.alarm_catalog_id]);
  }

  edit(item: AlarmCatalogEntry, event: Event): void {
    event.stopPropagation();
    this.router.navigate(['/alarm-catalog', item.alarm_catalog_id, 'edit']);
  }

  confirmDelete(item: AlarmCatalogEntry, event: Event): void {
    event.stopPropagation();
    this.deleteError = null;
    this.itemToDelete = item;
  }

  cancelDelete(): void {
    this.itemToDelete = null;
  }

  deleteConfirmed(): void {
    const target = this.itemToDelete;
    if (!target) {
      return;
    }
    this.deleting = true;
    this.service.delete(target.alarm_catalog_id).subscribe({
      next: () => {
        this.items = this.items.filter((i) => i.alarm_catalog_id !== target.alarm_catalog_id);
        this.itemToDelete = null;
        this.deleting = false;
      },
      error: (err) => {
        this.deleteError = err?.error?.detail || 'Failed to delete the alarm.';
        this.deleting = false;
      }
    });
  }

  // ---------------------------------------------------------------- bulk load

  onFileSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    this.selectedFile = input.files?.[0] ?? null;
    this.uploadResult = null;
    this.uploadError = null;
    this.showAllUploadErrors = false;
  }

  get visibleUploadErrors() {
    if (!this.uploadResult) {
      return [];
    }
    return this.showAllUploadErrors ? this.uploadResult.errors : this.uploadResult.errors.slice(0, 10);
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
        this.fetchData();
      },
      error: (err) => {
        this.uploadError = err?.error?.detail || 'Upload failed. Is the backend running?';
        this.uploading = false;
      }
    });
  }
}
