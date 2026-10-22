import { CommonModule } from '@angular/common';
import { Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';

import { Site } from '../../../core/models/site.model';
import { SiteService } from '../../../core/services/site.service';
import { HasPermissionDirective } from '../../../core/auth/has-permission.directive';

type SortColumn = 'site_code' | 'site_name' | 'primary_owner_name' | 'state' | 'rated_power_mw' | 'rated_energy_mwh' | 'commission_date';
type SortDirection = 'asc' | 'desc';

const PAGE_SIZE_OPTIONS = [10, 25, 50];

@Component({
  selector: 'app-site-list',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink, HasPermissionDirective],
  templateUrl: './site-list.component.html',
  styleUrl: './site-list.component.scss'
})
export class SiteListComponent implements OnInit {
  sites: Site[] = [];
  loading = true;
  error: string | null = null;
  siteToDelete: Site | null = null;
  deleting = false;
  deleteError: string | null = null;

  searchTerm = '';
  sortColumn: SortColumn = 'site_name';
  sortDirection: SortDirection = 'asc';

  pageSizeOptions = PAGE_SIZE_OPTIONS;
  pageSize = PAGE_SIZE_OPTIONS[0];
  currentPage = 1;

  constructor(private siteService: SiteService, private router: Router) {}

  ngOnInit(): void {
    this.fetchSites();
  }

  fetchSites(): void {
    this.loading = true;
    this.error = null;
    this.siteService.list().subscribe({
      next: (sites) => {
        this.sites = sites;
        this.loading = false;
      },
      error: () => {
        this.error = 'Could not load sites. Is the backend running?';
        this.loading = false;
      }
    });
  }

  get filteredSites(): Site[] {
    const term = this.searchTerm.trim().toLowerCase();
    if (!term) {
      return this.sites;
    }
    return this.sites.filter((site) =>
      [site.site_code, site.site_name, ...site.owners.map((o) => o.tenant_name), site.address, site.state, site.grid_operator, site.timezone]
        .filter((value): value is string => !!value)
        .some((value) => value.toLowerCase().includes(term))
    );
  }

  get sortedSites(): Site[] {
    const column = this.sortColumn;
    const direction = this.sortDirection === 'asc' ? 1 : -1;
    return [...this.filteredSites].sort((a, b) => {
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
    return this.filteredSites.length;
  }

  get totalPages(): number {
    return Math.max(1, Math.ceil(this.totalItems / this.pageSize));
  }

  get pagedSites(): Site[] {
    const page = Math.min(this.currentPage, this.totalPages);
    const start = (page - 1) * this.pageSize;
    return this.sortedSites.slice(start, start + this.pageSize);
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

  ownerSummary(site: Site): string {
    return site.owners
      .map((o) => `${o.tenant_name}${o.ownership_pct !== null ? ` ${o.ownership_pct}%` : ''}${o.is_primary_owner ? ' (primary)' : ''}`)
      .join(', ');
  }

  view(site: Site): void {
    this.router.navigate(['/sites', site.site_id]);
  }

  edit(site: Site, event: Event): void {
    event.stopPropagation();
    this.router.navigate(['/sites', site.site_id, 'edit']);
  }

  confirmDelete(site: Site, event: Event): void {
    event.stopPropagation();
    this.siteToDelete = site;
    this.deleteError = null;
  }

  cancelDelete(): void {
    this.siteToDelete = null;
    this.deleteError = null;
  }

  deleteConfirmed(): void {
    if (!this.siteToDelete) {
      return;
    }
    this.deleting = true;
    this.deleteError = null;
    this.siteService.delete(this.siteToDelete.site_id).subscribe({
      next: () => {
        this.sites = this.sites.filter((s) => s.site_id !== this.siteToDelete!.site_id);
        this.siteToDelete = null;
        this.deleting = false;
      },
      error: (err) => {
        this.deleteError = err?.error?.detail || 'Failed to delete site.';
        this.deleting = false;
      }
    });
  }
}
