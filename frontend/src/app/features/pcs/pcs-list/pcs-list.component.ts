import { CommonModule } from '@angular/common';
import { Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { forkJoin } from 'rxjs';
import { Router, RouterLink } from '@angular/router';

import { BatterySystem } from '../../../core/models/battery-system.model';
import { Pcs } from '../../../core/models/pcs.model';
import { BatterySystemService } from '../../../core/services/battery-system.service';
import { AssetLinksComponent } from '../../../shared/asset-links/asset-links.component';
import { PcsService } from '../../../core/services/pcs.service';

type SortColumn = 'pcs_code' | 'manufacturer' | 'model' | 'rated_power_kw' | 'rated_ac_voltage_v' | 'phases';
type SortDirection = 'asc' | 'desc';

const PAGE_SIZE_OPTIONS = [10, 25, 50];

@Component({
  selector: 'app-pcs-list',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink, AssetLinksComponent],
  templateUrl: './pcs-list.component.html',
  styleUrl: './pcs-list.component.scss'
})
export class PcsListComponent implements OnInit {
  items: Pcs[] = [];
  systemNameById = new Map<number, string>();
  loading = true;
  error: string | null = null;
  itemToDelete: Pcs | null = null;
  deleting = false;

  searchTerm = '';
  sortColumn: SortColumn = 'pcs_code';
  sortDirection: SortDirection = 'asc';

  pageSizeOptions = PAGE_SIZE_OPTIONS;
  pageSize = PAGE_SIZE_OPTIONS[0];
  currentPage = 1;

  constructor(
    private pcsService: PcsService,
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
      items: this.pcsService.list(),
      systems: this.batterySystemService.list()
    }).subscribe({
      next: ({ items, systems }) => {
        this.items = items;
        this.systemNameById = new Map(systems.map((system: BatterySystem) => [system.battery_system_id, system.system_name]));
        this.loading = false;
      },
      error: () => {
        this.error = 'Could not load PCS units. Is the backend running?';
        this.loading = false;
      }
    });
  }

  systemName(systemId: number): string {
    return this.systemNameById.get(systemId) ?? '—';
  }

  get filteredItems(): Pcs[] {
    const term = this.searchTerm.trim().toLowerCase();
    if (!term) {
      return this.items;
    }
    return this.items.filter((item) =>
      [item.pcs_code, item.manufacturer, item.model, item.serial_number, this.systemName(item.system_id)]
        .filter((value): value is string => !!value)
        .some((value) => value.toLowerCase().includes(term))
    );
  }

  get sortedItems(): Pcs[] {
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

  get pagedItems(): Pcs[] {
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

  view(item: Pcs): void {
    this.router.navigate(['/pcs', item.pcs_id]);
  }

  edit(item: Pcs, event: Event): void {
    event.stopPropagation();
    this.router.navigate(['/pcs', item.pcs_id, 'edit']);
  }

  confirmDelete(item: Pcs, event: Event): void {
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
    this.pcsService.delete(this.itemToDelete.pcs_id).subscribe({
      next: () => {
        this.items = this.items.filter((item) => item.pcs_id !== this.itemToDelete!.pcs_id);
        this.itemToDelete = null;
        this.deleting = false;
      },
      error: () => {
        this.error = 'Failed to delete PCS.';
        this.deleting = false;
        this.itemToDelete = null;
      }
    });
  }
}
