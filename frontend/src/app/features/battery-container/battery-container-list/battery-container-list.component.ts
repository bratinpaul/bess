import { CommonModule } from '@angular/common';
import { Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { forkJoin } from 'rxjs';
import { Router, RouterLink } from '@angular/router';

import { BatteryContainer } from '../../../core/models/battery-container.model';
import { BatterySystem } from '../../../core/models/battery-system.model';
import { BatteryContainerService } from '../../../core/services/battery-container.service';
import { BatterySystemService } from '../../../core/services/battery-system.service';

type SortColumn = 'container_number' | 'manufacturer' | 'installation_date' | 'status';
type SortDirection = 'asc' | 'desc';

const PAGE_SIZE_OPTIONS = [10, 25, 50];

@Component({
  selector: 'app-battery-container-list',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  templateUrl: './battery-container-list.component.html',
  styleUrl: './battery-container-list.component.scss'
})
export class BatteryContainerListComponent implements OnInit {
  containers: BatteryContainer[] = [];
  systemNameById = new Map<number, string>();
  loading = true;
  error: string | null = null;
  itemToDelete: BatteryContainer | null = null;
  deleting = false;

  searchTerm = '';
  sortColumn: SortColumn = 'container_number';
  sortDirection: SortDirection = 'asc';

  pageSizeOptions = PAGE_SIZE_OPTIONS;
  pageSize = PAGE_SIZE_OPTIONS[0];
  currentPage = 1;

  constructor(
    private containerService: BatteryContainerService,
    private batterySystemService: BatterySystemService,
    private router: Router
  ) {}

  ngOnInit(): void {
    this.fetchData();
  }

  fetchData(): void {
    this.loading = true;
    this.error = null;
    forkJoin({
      containers: this.containerService.list(),
      systems: this.batterySystemService.list()
    }).subscribe({
      next: ({ containers, systems }) => {
        this.containers = containers;
        this.systemNameById = new Map(systems.map((system: BatterySystem) => [system.battery_system_id, system.system_name]));
        this.loading = false;
      },
      error: () => {
        this.error = 'Could not load battery containers. Is the backend running?';
        this.loading = false;
      }
    });
  }

  systemName(batterySystemId: number): string {
    return this.systemNameById.get(batterySystemId) ?? '—';
  }

  get filteredItems(): BatteryContainer[] {
    const term = this.searchTerm.trim().toLowerCase();
    if (!term) {
      return this.containers;
    }
    return this.containers.filter((item) =>
      [item.container_number, item.manufacturer, item.status, this.systemName(item.battery_system_id)]
        .filter((value): value is string => !!value)
        .some((value) => value.toLowerCase().includes(term))
    );
  }

  get sortedItems(): BatteryContainer[] {
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

  get pagedItems(): BatteryContainer[] {
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

  view(item: BatteryContainer): void {
    this.router.navigate(['/battery-containers', item.container_id]);
  }

  edit(item: BatteryContainer, event: Event): void {
    event.stopPropagation();
    this.router.navigate(['/battery-containers', item.container_id, 'edit']);
  }

  confirmDelete(item: BatteryContainer, event: Event): void {
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
    this.containerService.delete(this.itemToDelete.container_id).subscribe({
      next: () => {
        this.containers = this.containers.filter((item) => item.container_id !== this.itemToDelete!.container_id);
        this.itemToDelete = null;
        this.deleting = false;
      },
      error: (err) => {
        this.error = err?.error?.detail || 'Failed to delete battery container.';
        this.deleting = false;
        this.itemToDelete = null;
      }
    });
  }
}
