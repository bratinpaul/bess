import { CommonModule } from '@angular/common';
import { Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';

import { EmsController } from '../../../core/models/ems-controller.model';
import { AssetLinksComponent } from '../../../shared/asset-links/asset-links.component';
import { EmsControllerService } from '../../../core/services/ems-controller.service';

type SortColumn = 'ems_code' | 'system_name';
type SortDirection = 'asc' | 'desc';

const PAGE_SIZE_OPTIONS = [10, 25, 50];

@Component({
  selector: 'app-ems-controller-list',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink, AssetLinksComponent],
  templateUrl: './ems-controller-list.component.html',
  styleUrl: './ems-controller-list.component.scss'
})
export class EmsControllerListComponent implements OnInit {
  items: EmsController[] = [];
  loading = true;
  error: string | null = null;
  itemToDelete: EmsController | null = null;
  deleting = false;
  deleteError: string | null = null;

  searchTerm = '';
  sortColumn: SortColumn = 'ems_code';
  sortDirection: SortDirection = 'asc';

  pageSizeOptions = PAGE_SIZE_OPTIONS;
  pageSize = PAGE_SIZE_OPTIONS[0];
  currentPage = 1;

  constructor(
    private service: EmsControllerService,
    private router: Router
  ) {}

  ngOnInit(): void {
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
        this.error = 'Could not load EMS controllers. Is the backend running?';
        this.loading = false;
      }
    });
  }

  get filteredItems(): EmsController[] {
    const term = this.searchTerm.trim().toLowerCase();
    if (!term) {
      return this.items;
    }
    return this.items.filter((item) =>
      [item.ems_code, item.system_name]
        .filter((value): value is string => !!value)
        .some((value) => value.toLowerCase().includes(term))
    );
  }

  get sortedItems(): EmsController[] {
    const column = this.sortColumn;
    const direction = this.sortDirection === 'asc' ? 1 : -1;
    return [...this.filteredItems].sort((a, b) => {
      const aValue = a[column];
      const bValue = b[column];
      if (aValue === null || aValue === undefined) return 1;
      if (bValue === null || bValue === undefined) return -1;
      return aValue.localeCompare(bValue, undefined, { numeric: true }) * direction;
    });
  }

  get totalItems(): number {
    return this.filteredItems.length;
  }

  get totalPages(): number {
    return Math.max(1, Math.ceil(this.totalItems / this.pageSize));
  }

  get pagedItems(): EmsController[] {
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

  onSearchChange(): void {
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
    if (page < 1 || page > this.totalPages) {
      return;
    }
    this.currentPage = page;
  }

  view(item: EmsController): void {
    this.router.navigate(['/ems-controllers', item.ems_id]);
  }

  edit(item: EmsController, event: Event): void {
    event.stopPropagation();
    this.router.navigate(['/ems-controllers', item.ems_id, 'edit']);
  }

  confirmDelete(item: EmsController, event: Event): void {
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
    this.service.delete(target.ems_id).subscribe({
      next: () => {
        this.items = this.items.filter((item) => item.ems_id !== target.ems_id);
        this.itemToDelete = null;
        this.deleting = false;
      },
      error: (err) => {
        // e.g. 409 while telemetry is recorded against it: keep the dialog open and say why
        this.deleteError = err?.error?.detail || 'Failed to delete EMS controller.';
        this.deleting = false;
      }
    });
  }
}
