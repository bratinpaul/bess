import { CommonModule } from '@angular/common';
import { Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';

import { HvacUnit } from '../../../core/models/hvac-unit.model';
import { AssetLinksComponent } from '../../../shared/asset-links/asset-links.component';
import { HvacUnitService } from '../../../core/services/hvac-unit.service';

type SortColumn = 'hvac_code' | 'system_name';
type SortDirection = 'asc' | 'desc';

const PAGE_SIZE_OPTIONS = [10, 25, 50];

@Component({
  selector: 'app-hvac-unit-list',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink, AssetLinksComponent],
  templateUrl: './hvac-unit-list.component.html',
  styleUrl: './hvac-unit-list.component.scss'
})
export class HvacUnitListComponent implements OnInit {
  items: HvacUnit[] = [];
  loading = true;
  error: string | null = null;
  itemToDelete: HvacUnit | null = null;
  deleting = false;
  deleteError: string | null = null;

  searchTerm = '';
  sortColumn: SortColumn = 'hvac_code';
  sortDirection: SortDirection = 'asc';

  pageSizeOptions = PAGE_SIZE_OPTIONS;
  pageSize = PAGE_SIZE_OPTIONS[0];
  currentPage = 1;

  constructor(
    private service: HvacUnitService,
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
        this.error = 'Could not load HVAC units. Is the backend running?';
        this.loading = false;
      }
    });
  }

  get filteredItems(): HvacUnit[] {
    const term = this.searchTerm.trim().toLowerCase();
    if (!term) {
      return this.items;
    }
    return this.items.filter((item) =>
      [item.hvac_code, item.system_name]
        .filter((value): value is string => !!value)
        .some((value) => value.toLowerCase().includes(term))
    );
  }

  get sortedItems(): HvacUnit[] {
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

  get pagedItems(): HvacUnit[] {
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

  view(item: HvacUnit): void {
    this.router.navigate(['/hvac-units', item.hvac_id]);
  }

  edit(item: HvacUnit, event: Event): void {
    event.stopPropagation();
    this.router.navigate(['/hvac-units', item.hvac_id, 'edit']);
  }

  confirmDelete(item: HvacUnit, event: Event): void {
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
    this.service.delete(target.hvac_id).subscribe({
      next: () => {
        this.items = this.items.filter((item) => item.hvac_id !== target.hvac_id);
        this.itemToDelete = null;
        this.deleting = false;
      },
      error: (err) => {
        // e.g. 409 while telemetry is recorded against it: keep the dialog open and say why
        this.deleteError = err?.error?.detail || 'Failed to delete HVAC unit.';
        this.deleting = false;
      }
    });
  }
}
