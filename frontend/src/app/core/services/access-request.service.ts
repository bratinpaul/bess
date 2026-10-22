import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { AUTH_URL } from '../auth/auth.config';

export type AccessRequestStatus = 'PENDING' | 'APPROVED' | 'REJECTED';

export interface AccessRequest {
  request_id: number;
  full_name: string;
  email: string;
  organisation: string | null;
  reason: string;
  status: AccessRequestStatus;
  requested_at: string;
  reviewed_at: string | null;
  reviewed_by: string | null;
  role_code: string | null;
  role_name: string | null;
  tenant_id: number | null;
  decision_note: string | null;
  user_id: string | null;
}

export interface AssignableRole {
  role_code: string;
  role_name: string;
  is_tenant_scoped: boolean;
  description: string | null;
}

export interface SignupRequest {
  full_name: string;
  email: string;
  organisation: string | null;
  reason: string;
  password: string;
}

/** Self-service sign-up (public) and the Admin review of access requests (/api/auth/...). */
@Injectable({ providedIn: 'root' })
export class AccessRequestService {
  constructor(private http: HttpClient) {}

  signup(body: SignupRequest): Observable<{ message: string }> {
    return this.http.post<{ message: string }>(`${AUTH_URL}/signup`, body);
  }

  passwordPolicy(): Observable<{ min_length: number; rules: string[] }> {
    return this.http.get<{ min_length: number; rules: string[] }>(`${AUTH_URL}/password-policy`);
  }

  list(status?: AccessRequestStatus | null): Observable<{ requests: AccessRequest[]; roles: AssignableRole[]; pending: number | null }> {
    const params: Record<string, string> = status ? { status } : {};
    return this.http.get<{ requests: AccessRequest[]; roles: AssignableRole[]; pending: number | null }>(
      `${AUTH_URL}/access-requests`, { params });
  }

  approve(id: number, roleCode: string, tenantId: number | null, note: string | null): Observable<AccessRequest> {
    return this.http.post<AccessRequest>(`${AUTH_URL}/access-requests/${id}/approve`, { role_code: roleCode, tenant_id: tenantId, note });
  }

  reject(id: number, note: string | null): Observable<AccessRequest> {
    return this.http.post<AccessRequest>(`${AUTH_URL}/access-requests/${id}/reject`, { note });
  }
}
