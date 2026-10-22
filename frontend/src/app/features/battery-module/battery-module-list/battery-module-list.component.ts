import { CommonModule } from '@angular/common';
import { Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { forkJoin } from 'rxjs';
import { Router, RouterLink } from '@angular/router';

import { BatteryModule } from '../../../core/models/battery-module.model';
import { BatteryPack } from '../../../core/models/battery-pack.model';
import { AssetLinksComponent } from '../../../shared/asset-links/asset-links.component';
import { BatteryModuleService } from '../../../core/services/battery-module.service';
import { BatteryPackService } from '../../../core/services/battery-pack.service';

type SortColumn = 'serial_number' | 'chemistry' | 'nominal_voltage' | 'capacity_ah' | 'status';
type SortDirection = 'asc' | 'desc';

const PAGE_SIZE_OPTIONS = [10, 25, 50];

@Component({
  selector: 'app-battery-module-list',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink, AssetLinksComponent],
  templateUrl: './battery-module-list.component.html',
  styleUrl: './battery-module-list.component.scss'
})
export class BatteryModuleListComponent implements OnInit {
  modules: BatteryModule[] = [];
  packNumberById = new Map<number, string>();
  loading = true;
  error: string | null = null;
  itemToDelete: BatteryModule | null = null;
  deleting = false;

  searchTerm = '';
  sortColumn: SortColumn = 'serial_number';
  sortDirection: SortDirection = 'asc';

  pageSizeOptions = PAGE_SIZE_OPTIONS;
  pageSize = PAGE_SIZE_OPTIONS[0];
  currentPage = 1;

  constructor(
    private moduleService: BatteryModuleService,
    private packService: BatteryPackService,
    private router: Router
  ) {}

  ngOnInit(): void {
    this.fetchData();
  }

  fetchData(): void {
    this.loading = true;
    this.error = null;
    forkJoin({
      modules: this.moduleService.list(),
      packs: this.packService.list()
    }).subscribe({
      next: ({ modules, packs }) => {
        this.modules = modules;
        this.packNumberById = new Map(
          packs.map((pack: BatteryPack) => [pack.pack_id, pack.pack_number || String(pack.pack_id)])
        );
        this.loading = false;
      },
      error: () => {
        this.error = 'Could not load battery modules. Is the backend running?';
        this.loading = false;
      }
    });
  }

  packNumber(packId: number): string {
    return this.packNumberById.get(packId) ?? '—';
  }

  get filteredItems(): BatteryModule[] {
    const term = this.searchTerm.trim().toLowerCase();
    if (!term) {
      return this.modules;
    }
    return this.modules.filter((item) =>
      [item.serial_number, item.chemistry, item.status, this.packNumber(item.pack_id)]
        .filter((value): value is string => !!value)
        .some((value) => value.toLowerCase().includes(term))
    );
  }

  get sortedItems(): BatteryModule[] {
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

  get pagedItems(): BatteryModule[] {
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

  view(item: BatteryModule): void {
    this.router.navigate(['/battery-modules', item.module_id]);
  }

  edit(item: BatteryModule, event: Event): void {
    event.stopPropagation();
    this.router.navigate(['/battery-modules', item.module_id, 'edit']);
  }

  confirmDelete(item: BatteryModule, event: Event): void {
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
    this.moduleService.delete(this.itemToDelete.module_id).subscribe({
      next: () => {
        this.modules = this.modules.filter((item) => item.module_id !== this.itemToDelete!.module_id);
        this.itemToDelete = null;
        this.deleting = false;
      },
      error: () => {
        this.error = 'Failed to delete battery module.';
        this.deleting = false;
        this.itemToDelete = null;
      }
    });
  }
}
