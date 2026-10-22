import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { Tenant, TenantContact, TenantContactInput, TenantDetail, TenantInput } from '../models/tenant.model';

@Injectable({ providedIn: 'root' })
export class TenantService {
  private readonly baseUrl = 'http://localhost:8000/api/tenants';

  constructor(private http: HttpClient) {}

  list(): Observable<Tenant[]> {
    return this.http.get<Tenant[]>(this.baseUrl);
  }

  /** Allowed tenant types (the tenant_type Postgres enum), in their defined order. */
  types(): Observable<string[]> {
    return this.http.get<string[]>(`${this.baseUrl}/types`);
  }

  /** Tenant with its contacts and owned sites. */
  get(tenantId: number): Observable<TenantDetail> {
    return this.http.get<TenantDetail>(`${this.baseUrl}/${tenantId}`);
  }

  create(payload: TenantInput): Observable<TenantDetail> {
    return this.http.post<TenantDetail>(this.baseUrl, payload);
  }

  update(tenantId: number, payload: TenantInput): Observable<TenantDetail> {
    return this.http.put<TenantDetail>(`${this.baseUrl}/${tenantId}`, payload);
  }

  /** Also removes the tenant's contacts and site-ownership links (database cascade). */
  delete(tenantId: number): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/${tenantId}`);
  }

  createContact(tenantId: number, payload: TenantContactInput): Observable<TenantContact> {
    return this.http.post<TenantContact>(`${this.baseUrl}/${tenantId}/contacts`, payload);
  }

  updateContact(tenantId: number, contactId: number, payload: TenantContactInput): Observable<TenantContact> {
    return this.http.put<TenantContact>(`${this.baseUrl}/${tenantId}/contacts/${contactId}`, payload);
  }

  deleteContact(tenantId: number, contactId: number): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/${tenantId}/contacts/${contactId}`);
  }
}
