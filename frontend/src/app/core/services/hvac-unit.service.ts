import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { HvacUnit, HvacUnitInput } from '../models/hvac-unit.model';

@Injectable({ providedIn: 'root' })
export class HvacUnitService {
  private readonly baseUrl = 'http://localhost:8000/api/hvac-units';

  constructor(private http: HttpClient) {}

  list(): Observable<HvacUnit[]> {
    return this.http.get<HvacUnit[]>(this.baseUrl);
  }

  get(id: number): Observable<HvacUnit> {
    return this.http.get<HvacUnit>(`${this.baseUrl}/${id}`);
  }

  create(payload: HvacUnitInput): Observable<HvacUnit> {
    return this.http.post<HvacUnit>(this.baseUrl, payload);
  }

  update(id: number, payload: HvacUnitInput): Observable<HvacUnit> {
    return this.http.put<HvacUnit>(`${this.baseUrl}/${id}`, payload);
  }

  /** Refused (409) while telemetry is recorded against it. */
  delete(id: number): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/${id}`);
  }
}
