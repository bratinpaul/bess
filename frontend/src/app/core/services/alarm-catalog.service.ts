import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import {
  AlarmCatalogEntry,
  AlarmCatalogInput,
  AlarmCatalogLookups,
  BulkAlarmCatalogResult
} from '../models/alarm-catalog.model';

@Injectable({ providedIn: 'root' })
export class AlarmCatalogService {
  private readonly baseUrl = 'http://localhost:8000/api/alarm-catalog';

  constructor(private http: HttpClient) {}

  list(): Observable<AlarmCatalogEntry[]> {
    return this.http.get<AlarmCatalogEntry[]>(this.baseUrl);
  }

  lookups(): Observable<AlarmCatalogLookups> {
    return this.http.get<AlarmCatalogLookups>(`${this.baseUrl}/lookups`);
  }

  get(id: number): Observable<AlarmCatalogEntry> {
    return this.http.get<AlarmCatalogEntry>(`${this.baseUrl}/${id}`);
  }

  create(payload: AlarmCatalogInput): Observable<AlarmCatalogEntry> {
    return this.http.post<AlarmCatalogEntry>(this.baseUrl, payload);
  }

  update(id: number, payload: AlarmCatalogInput): Observable<AlarmCatalogEntry> {
    return this.http.put<AlarmCatalogEntry>(`${this.baseUrl}/${id}`, payload);
  }

  delete(id: number): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/${id}`);
  }

  /** .xlsx (its 'Alarm Catalog' sheet) or .csv; existing (source, alarm_code) entries are updated. */
  bulkUpload(file: File): Observable<BulkAlarmCatalogResult> {
    const form = new FormData();
    form.append('file', file);
    return this.http.post<BulkAlarmCatalogResult>(`${this.baseUrl}/bulk`, form);
  }
}
