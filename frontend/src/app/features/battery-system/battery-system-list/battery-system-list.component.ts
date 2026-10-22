import { CommonModule } from '@angular/common';
import { Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { forkJoin } from 'rxjs';
import { Router, RouterLink } from '@angular/router';

import { BatterySystem } from '../../../core/models/battery-system.model';
import { Site } from '../../../core/models/site.model';
import { AssetLinksComponent } from '../../../shared/asset-links/asset-links.component';
import { BatterySystemService } from '../../../core/services/battery-system.service';
import { SiteService } from '../../../core/services/site.service';

type SortColumn = 'system_name' | 'manufacturer' | 'chemistry_code' | 'rated_power_mw' | 'rated_energy_mwh' | 'status';
type SortDirection = 'asc' | 'desc';

const PAGE_SIZE_OPTIONS = [10, 25, 50];

@Component({
  selector: 'app-battery-system-list',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink, AssetLinksComponent],
  templateUrl: './battery-system-list.component.html',
  styleUrl: './battery-system-list.component.scss'
})
export class BatterySystemListComponent implements OnInit {
  batterySystems: BatterySystem[] = [];
  siteNameById = new Map<number, string>();
  loading = true;
  error: string | null = null;
  itemToDelete: BatterySystem | null = null;
  deleting = false;

  searchTerm = '';
  sortColumn: SortColumn = 'system_name';
  sortDirection: SortDirection = 'asc';

  pageSizeOptions = PAGE_SIZE_OPTIONS;
  pageSize = PAGE_SIZE_OPTIONS[0];
  currentPage = 1;

  constructor(
    private batterySystemService: BatterySystemService,
    private siteService: SiteService,
    private router: Router
  ) {}

  ngOnInit(): void {
    this.fetchData();
  }

  fetchData(): void {
    this.loading = true;
    this.error = null;
    forkJoin({
      batterySystems: this.batterySystemService.list(),
      sites: this.siteService.list()
    }).subscribe({
      next: ({ batterySystems, sites }) => {
        this.batterySystems = batterySystems;
        this.siteNameById = new Map(sites.map((site: Site) => [site.site_id, site.site_name]));
        this.loading = false;
      },
      error: () => {
        this.error = 'Could not load battery systems. Is the backend running?';
        this.loading = false;
      }
    });
  }

  siteName(siteId: number): string {
    return this.siteNameById.get(siteId) ?? '—';
  }

  get filteredItems(): BatterySystem[] {
    const term = this.searchTerm.trim().toLowerCase();
    if (!term) {
      return this.batterySystems;
    }
    return this.batterySystems.filter((item) =>
      [item.system_name, item.manufacturer, item.model, item.status, item.chemistry_code, item.bms_firmware, this.siteName(item.site_id)]
        .filter((value): value is string => !!value)
        .some((value) => value.toLowerCase().includes(term))
    );
  }

  get sortedItems(): BatterySystem[] {
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

  get pagedItems(): BatterySystem[] {
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

  view(item: BatterySystem): void {
    this.router.navigate(['/battery-systems', item.battery_system_id]);
  }

  edit(item: BatterySystem, event: Event): void {
    event.stopPropagation();
    this.router.navigate(['/battery-systems', item.battery_system_id, 'edit']);
  }

  confirmDelete(item: BatterySystem, event: Event): void {
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
    this.batterySystemService.delete(this.itemToDelete.battery_system_id).subscribe({
      next: () => {
        this.batterySystems = this.batterySystems.filter(
          (item) => item.battery_system_id !== this.itemToDelete!.battery_system_id
        );
        this.itemToDelete = null;
        this.deleting = false;
      },
      error: (err) => {
        this.error = err?.error?.detail || 'Failed to delete battery system.';
        this.deleting = false;
        this.itemToDelete = null;
      }
    });
  }
}
