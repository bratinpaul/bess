import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { Site, SiteCreateInput, SiteUpdateInput } from '../models/site.model';

@Injectable({ providedIn: 'root' })
export class SiteService {
  private readonly baseUrl = 'http://localhost:8000/api/sites';

  constructor(private http: HttpClient) {}

  list(): Observable<Site[]> {
    return this.http.get<Site[]>(this.baseUrl);
  }

  get(siteId: number): Observable<Site> {
    return this.http.get<Site>(`${this.baseUrl}/${siteId}`);
  }

  create(payload: SiteCreateInput): Observable<Site> {
    return this.http.post<Site>(this.baseUrl, payload);
  }

  update(siteId: number, payload: SiteUpdateInput): Observable<Site> {
    return this.http.put<Site>(`${this.baseUrl}/${siteId}`, payload);
  }

  delete(siteId: number): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/${siteId}`);
  }
}
