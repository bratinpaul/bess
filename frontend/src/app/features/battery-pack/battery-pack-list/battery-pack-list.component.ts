import { CommonModule } from '@angular/common';
import { Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { forkJoin } from 'rxjs';
import { Router, RouterLink } from '@angular/router';

import { BatteryContainer } from '../../../core/models/battery-container.model';
import { BatteryPack } from '../../../core/models/battery-pack.model';
import { BatteryContainerService } from '../../../core/services/battery-container.service';
import { BatteryPackService } from '../../../core/services/battery-pack.service';

type SortColumn = 'pack_number' | 'nominal_voltage' | 'nominal_capacity_ah' | 'status';
type SortDirection = 'asc' | 'desc';

const PAGE_SIZE_OPTIONS = [10, 25, 50];

@Component({
  selector: 'app-battery-pack-list',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  templateUrl: './battery-pack-list.component.html',
  styleUrl: './battery-pack-list.component.scss'
})
export class BatteryPackListComponent implements OnInit {
  packs: BatteryPack[] = [];
  containerNumberById = new Map<number, string>();
  loading = true;
  error: string | null = null;
  itemToDelete: BatteryPack | null = null;
  deleting = false;

  searchTerm = '';
  sortColumn: SortColumn = 'pack_number';
  sortDirection: SortDirection = 'asc';

  pageSizeOptions = PAGE_SIZE_OPTIONS;
  pageSize = PAGE_SIZE_OPTIONS[0];
  currentPage = 1;

  constructor(
    private packService: BatteryPackService,
    private containerService: BatteryContainerService,
    private router: Router
  ) {}

  ngOnInit(): void {
    this.fetchData();
  }

  fetchData(): void {
    this.loading = true;
    this.error = null;
    forkJoin({
      packs: this.packService.list(),
      containers: this.containerService.list()
    }).subscribe({
      next: ({ packs, containers }) => {
        this.packs = packs;
        this.containerNumberById = new Map(
          containers.map((container: BatteryContainer) => [
            container.container_id,
            container.container_number || String(container.container_id)
          ])
        );
        this.loading = false;
      },
      error: () => {
        this.error = 'Could not load battery packs. Is the backend running?';
        this.loading = false;
      }
    });
  }

  containerNumber(containerId: number): string {
    return this.containerNumberById.get(containerId) ?? '—';
  }

  get filteredItems(): BatteryPack[] {
    const term = this.searchTerm.trim().toLowerCase();
    if (!term) {
      return this.packs;
    }
    return this.packs.filter((item) =>
      [item.pack_number, item.status, this.containerNumber(item.container_id)]
        .filter((value): value is string => !!value)
        .some((value) => value.toLowerCase().includes(term))
    );
  }

  get sortedItems(): BatteryPack[] {
    const column = this.sortColumn;
    const direction = this.sortDirection === 'asc' ? 1 : -1;
    return [...this.filteredItems].sort((a, b) => {
      const aValue = a[column];
      const bValue = b[column];
      if (aValue === null || aValue === undefined) return 1;
      if (bValue === null || bValue === undefined) return -1;
      if (aValue < bValue) return -1 * direction;
      if (aValue > bValue) return 1 * direction;
      return 0;
    });
  }

  get totalItems(): number {
    return this.filteredItems.length;
  }

  get totalPages(): number {
    return Math.max(1, Math.ceil(this.totalItems / this.pageSize));
  }

  get pagedItems(): BatteryPack[] {
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

  view(item: BatteryPack): void {
    this.router.navigate(['/battery-packs', item.pack_id]);
  }

  edit(item: BatteryPack, event: Event): void {
    event.stopPropagation();
    this.router.navigate(['/battery-packs', item.pack_id, 'edit']);
  }

  confirmDelete(item: BatteryPack, event: Event): void {
    event.stopPropagation();
    this.itemToDelete = item;
  }

  cancelDelete(): void {
    this.itemToDelete = null;
  }

  deleteConfirmed(): void {
    if (!this.itemToDelete) {
      return;
    }
    this.deleting = true;
    this.packService.delete(this.itemToDelete.pack_id).subscribe({
      next: () => {
        this.packs = this.packs.filter((item) => item.pack_id !== this.itemToDelete!.pack_id);
        this.itemToDelete = null;
        this.deleting = false;
      },
      error: (err) => {
        this.error = err?.error?.detail || 'Failed to delete battery pack.';
        this.deleting = false;
        this.itemToDelete = null;
      }
    });
  }
}
