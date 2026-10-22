import { CommonModule } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { Component, OnInit, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { BACKEND_URL } from '../../../core/auth/auth.config';
import { AccessRequest, AccessRequestService, AccessRequestStatus, AssignableRole } from '../../../core/services/access-request.service';

interface Decision {
  role: string;
  tenant: number | null;
  note: string;
  busy: boolean;
  error: string | null;
}

/** Administration -> Access Requests: review sign-ups, assign a role (and a tenant for tenant-scoped roles) or decline. */
@Component({
  selector: 'app-access-requests',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './access-requests.component.html',
  styleUrl: './access-requests.component.scss'
})
export class AccessRequestsComponent implements OnInit {
  private service = inject(AccessRequestService);
  private http = inject(HttpClient);

  filter: AccessRequestStatus | null = 'PENDING';
  requests: AccessRequest[] = [];
  roles: AssignableRole[] = [];
  tenants: { tenant_id: number; name: string }[] = [];
  decisions: Record<number, Decision> = {};
  loading = false;
  error: string | null = null;
  flash: string | null = null;

  ngOnInit(): void {
    this.http.get<{ tenant_id: number; name: string }[]>(`${BACKEND_URL}/api/tenants`).subscribe({
      next: (t) => (this.tenants = t.map((x) => ({ tenant_id: x.tenant_id, name: x.name })))
    });
    this.load();
  }

  load(): void {
    this.loading = true;
    this.error = null;
    this.service.list(this.filter).subscribe({
      next: (r) => {
        this.loading = false;
        this.requests = r.requests;
        this.roles = r.roles;
        for (const q of r.requests) {
          this.decisions[q.request_id] ??= { role: '', tenant: null, note: '', busy: false, error: null };
        }
      },
      error: (err) => {
        this.loading = false;
        this.error = err?.status === 0 ? 'Cannot reach the server (port 8000).' : 'Could not load the requests.';
      }
    });
  }

  setFilter(f: AccessRequestStatus | null): void {
    this.filter = f;
    this.load();
  }

  role(code: string): AssignableRole | undefined {
    return this.roles.find((r) => r.role_code === code);
  }

  tenantName(id: number | null): string {
    return this.tenants.find((t) => t.tenant_id === id)?.name ?? (id ? `#${id}` : '');
  }

  canApprove(q: AccessRequest): boolean {
    const d = this.decisions[q.request_id];
    if (!d || !d.role || d.busy) {
      return false;
    }
    return !this.role(d.role)?.is_tenant_scoped || !!d.tenant;
  }

  approve(q: AccessRequest): void {
    const d = this.decisions[q.request_id];
    d.busy = true;
    d.error = null;
    const scoped = this.role(d.role)?.is_tenant_scoped;
    this.service.approve(q.request_id, d.role, scoped ? d.tenant : null, d.note.trim() || null).subscribe({
      next: (r) => {
        d.busy = false;
        this.flash = `${q.full_name} approved as ${r.role_name} - they can sign in now.`;
        this.load();
      },
      error: (err) => {
        d.busy = false;
        d.error = typeof err?.error?.detail === 'string' ? err.error.detail : 'Approval failed.';
      }
    });
  }

  reject(q: AccessRequest): void {
    const d = this.decisions[q.request_id];
    d.busy = true;
    d.error = null;
    this.service.reject(q.request_id, d.note.trim() || null).subscribe({
      next: () => {
        d.busy = false;
        this.flash = `Request from ${q.full_name} declined.`;
        this.load();
      },
      error: (err) => {
        d.busy = false;
        d.error = typeof err?.error?.detail === 'string' ? err.error.detail : 'Could not decline the request.';
      }
    });
  }
}
