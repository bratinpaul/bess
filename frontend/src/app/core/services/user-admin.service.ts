import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { BACKEND_URL } from '../auth/auth.config';

export interface AdminPrivilege {
  privilege_id: number;
  code: string;
  resource: string;
  action: string;
  module_label: string | null;
  description: string | null;
  source: 'system' | 'custom';
  enforced: boolean;
  registered_by: string[];
  roles: string[];
}

export interface AdminRole {
  role_code: string;
  role_name: string;
  description: string | null;
  is_tenant_scoped: boolean;
  is_system: boolean;
  version: number;
  updated_at: string;
  user_count: number;
  privilege_count: number;
}

export interface RbacMatrix {
  roles: AdminRole[];
  privileges: AdminPrivilege[];
  grants: Record<string, string[]>;
  locked: [string, string][];
}

export interface MatrixSaveResult extends RbacMatrix {
  changed_roles: string[];
  affected_users: number;
}

export interface AdminUser {
  id: string;
  email: string;
  full_name: string | null;
  role_code: string;
  role_name: string;
  tenant_id: number | null;
  tenant_name: string | null;
  is_active: boolean;
  is_service_account: boolean;
  must_change_password: boolean;
  locked: boolean;
  failed_logins: number;
  last_login_at: string | null;
  created_at: string;
}

export interface RbacChange {
  change_id: number;
  ts: string;
  actor_email: string;
  request_id: string | null;
  entity: string;
  action: string;
  target: string;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
}

export interface TokenPreview {
  role: string;
  role_name: string;
  rv: number;
  tenant_scoped: boolean;
  perms: string[];
}

/** Administration -> User Management API (/api/admin/*, admin:read / write / delete). */
@Injectable({ providedIn: 'root' })
export class UserAdminService {
  private http = inject(HttpClient);
  private readonly base = `${BACKEND_URL}/api/admin`;

  privileges(): Observable<AdminPrivilege[]> {
    return this.http.get<AdminPrivilege[]>(`${this.base}/privileges`);
  }
  addPrivilege(body: { resource: string; action: string; module_label: string | null; description: string | null }): Observable<AdminPrivilege> {
    return this.http.post<AdminPrivilege>(`${this.base}/privileges`, body);
  }
  editPrivilege(id: number, body: { module_label: string | null; description: string | null }): Observable<AdminPrivilege> {
    return this.http.patch<AdminPrivilege>(`${this.base}/privileges/${id}`, body);
  }
  deletePrivilege(id: number): Observable<unknown> {
    return this.http.delete(`${this.base}/privileges/${id}`);
  }

  roles(): Observable<AdminRole[]> {
    return this.http.get<AdminRole[]>(`${this.base}/roles`);
  }
  addRole(body: { role_code: string; role_name: string; description: string | null; is_tenant_scoped: boolean; copy_from: string | null }): Observable<AdminRole> {
    return this.http.post<AdminRole>(`${this.base}/roles`, body);
  }
  editRole(code: string, body: Partial<Pick<AdminRole, 'role_name' | 'description' | 'is_tenant_scoped'>>): Observable<AdminRole> {
    return this.http.patch<AdminRole>(`${this.base}/roles/${encodeURIComponent(code)}`, body);
  }
  deleteRole(code: string): Observable<unknown> {
    return this.http.delete(`${this.base}/roles/${encodeURIComponent(code)}`);
  }

  matrix(): Observable<RbacMatrix> {
    return this.http.get<RbacMatrix>(`${this.base}/rbac-matrix`);
  }
  saveMatrix(added: [string, string][], removed: [string, string][]): Observable<MatrixSaveResult> {
    return this.http.put<MatrixSaveResult>(`${this.base}/rbac-matrix`, { added, removed });
  }
  tokenPreview(role: string): Observable<TokenPreview> {
    return this.http.get<TokenPreview>(`${this.base}/token-preview/${encodeURIComponent(role)}`);
  }
  changes(params: { entity?: string; actor?: string; limit?: number; offset?: number }): Observable<{ total: number; items: RbacChange[] }> {
    const p: Record<string, string> = {};
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== '' && v !== null) p[k] = String(v);
    }
    return this.http.get<{ total: number; items: RbacChange[] }>(`${this.base}/rbac-changes`, { params: p });
  }

  users(): Observable<AdminUser[]> {
    return this.http.get<AdminUser[]>(`${this.base}/users`);
  }
  tenants(): Observable<{ tenant_id: number; name: string }[]> {
    return this.http.get<{ tenant_id: number; name: string }[]>(`${this.base}/tenants`);
  }
  addUser(body: { email: string; full_name: string; role_code: string; tenant_id: number | null }): Observable<{ user: AdminUser; temporary_password: string }> {
    return this.http.post<{ user: AdminUser; temporary_password: string }>(`${this.base}/users`, body);
  }
  editUser(id: string, body: { full_name?: string; role_code?: string; tenant_id?: number | null; is_active?: boolean }): Observable<AdminUser> {
    return this.http.patch<AdminUser>(`${this.base}/users/${id}`, body);
  }
  unlockUser(id: string): Observable<AdminUser> {
    return this.http.post<AdminUser>(`${this.base}/users/${id}/unlock`, {});
  }
  resetPassword(id: string): Observable<{ user: AdminUser; temporary_password: string }> {
    return this.http.post<{ user: AdminUser; temporary_password: string }>(`${this.base}/users/${id}/reset-password`, {});
  }
}

/** The API's error text (409 safeguards, 422 validation) for a banner. */
export function apiError(err: unknown, fallback: string): string {
  const e = err as { status?: number; error?: { detail?: unknown } };
  if (e?.status === 0) return 'Cannot reach the server (port 8000).';
  const d = e?.error?.detail;
  if (typeof d === 'string') return d;
  if (Array.isArray(d) && d.length) return d.map((x: { msg?: string }) => x.msg ?? '').filter(Boolean).join('; ');
  return fallback;
}
