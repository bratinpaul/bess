import { CommonModule } from '@angular/common';
import { Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';

import { TENANT_STATUSES, Tenant, TenantStatus } from '../../../core/models/tenant.model';
import { TenantService } from '../../../core/services/tenant.service';

type SortColumn =
  | 'name'
  | 'tenant_type'
  | 'city'
  | 'country'
  | 'primary_contact_name'
  | 'status'
  | 'contact_count'
  | 'site_count';
type SortDirection = 'asc' | 'desc';

const PAGE_SIZE_OPTIONS = [10, 25, 50];

@Component({
  selector: 'app-tenant-list',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  templateUrl: './tenant-list.component.html'
})
export class TenantListComponent implements OnInit {
  tenants: Tenant[] = [];
  loading = true;
  error: string | null = null;
  tenantToDelete: Tenant | null = null;
  deleting = false;
  deleteError: string | null = null;

  searchTerm = '';
  statusFilter: TenantStatus | '' = '';
  statuses = TENANT_STATUSES;
  readonly columns: { key: SortColumn; label: string }[] = [
    { key: 'name', label: 'Name' },
    { key: 'tenant_type', label: 'Type' },
    { key: 'city', label: 'City' },
    { key: 'country', label: 'Country' },
    { key: 'primary_contact_name', label: 'Primary Contact' },
    { key: 'status', label: 'Status' },
    { key: 'contact_count', label: 'Contacts' },
    { key: 'site_count', label: 'Sites' }
  ];
  sortColumn: SortColumn = 'name';
  sortDirection: SortDirection = 'asc';

  pageSizeOptions = PAGE_SIZE_OPTIONS;
  pageSize = PAGE_SIZE_OPTIONS[0];
  currentPage = 1;

  constructor(private tenantService: TenantService, private router: Router) {}

  ngOnInit(): void {
    this.fetchTenants();
  }

  fetchTenants(): void {
    this.loading = true;
    this.error = null;
    this.tenantService.list().subscribe({
      next: (tenants) => {
        this.tenants = tenants;
        this.loading = false;
      },
      error: () => {
        this.error = 'Could not load tenants. Is the backend running?';
        this.loading = false;
      }
    });
  }

  get filteredTenants(): Tenant[] {
    const term = this.searchTerm.trim().toLowerCase();
    return this.tenants.filter((t) => {
      if (this.statusFilter && t.status !== this.statusFilter) {
        return false;
      }
      if (!term) {
        return true;
      }
      return [t.name, t.legal_name, t.tenant_type, t.city, t.state_province, t.country, t.email, t.phone, t.primary_contact_name]
        .filter((value): value is string => !!value)
        .some((value) => value.toLowerCase().includes(term));
    });
  }

  get sortedTenants(): Tenant[] {
    const column = this.sortColumn;
    const direction = this.sortDirection === 'asc' ? 1 : -1;
    return [...this.filteredTenants].sort((a, b) => {
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
    return this.filteredTenants.length;
  }

  get totalPages(): number {
    return Math.max(1, Math.ceil(this.totalItems / this.pageSize));
  }

  get pagedTenants(): Tenant[] {
    const page = Math.min(this.currentPage, this.totalPages);
    const start = (page - 1) * this.pageSize;
    return this.sortedTenants.slice(start, start + this.pageSize);
  }

  get rangeStart(): number {
    return this.totalItems === 0 ? 0 : (this.currentPage - 1) * this.pageSize + 1;
  }

  get rangeEnd(): number {
    return Math.min(this.currentPage * this.pageSize, this.totalItems);
  }

  onFilterChange(): void {
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

  view(tenant: Tenant): void {
    this.router.navigate(['/tenants', tenant.tenant_id]);
  }

  edit(tenant: Tenant, event: Event): void {
    event.stopPropagation();
    this.router.navigate(['/tenants', tenant.tenant_id, 'edit']);
  }

  confirmDelete(tenant: Tenant, event: Event): void {
    event.stopPropagation();
    this.tenantToDelete = tenant;
    this.deleteError = null;
  }

  /** What else the database removes with the tenant (ON DELETE CASCADE), or null if nothing. */
  deleteImpact(t: Tenant): string | null {
    const parts: string[] = [];
    if (t.contact_count > 0) {
      parts.push(`its ${t.contact_count} contact${t.contact_count === 1 ? '' : 's'}`);
    }
    if (t.site_count > 0) {
      parts.push(`its ownership of ${t.site_count} site${t.site_count === 1 ? '' : 's'} (the sites themselves are kept)`);
    }
    return parts.length ? `This also removes ${parts.join(' and ')}.` : null;
  }

  cancelDelete(): void {
    this.tenantToDelete = null;
    this.deleteError = null;
  }

  deleteConfirmed(): void {
    if (!this.tenantToDelete) {
      return;
    }
    this.deleting = true;
    this.deleteError = null;
    this.tenantService.delete(this.tenantToDelete.tenant_id).subscribe({
      next: () => {
        this.tenants = this.tenants.filter((t) => t.tenant_id !== this.tenantToDelete!.tenant_id);
        this.tenantToDelete = null;
        this.deleting = false;
      },
      error: (err) => {
        this.deleteError = err?.error?.detail || 'Failed to delete tenant.';
        this.deleting = false;
      }
    });
  }
}
