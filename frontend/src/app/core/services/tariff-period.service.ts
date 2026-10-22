import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { TariffPeriod, TariffPeriodInput, TariffPeriodLookups } from '../models/tariff-period.model';

@Injectable({ providedIn: 'root' })
export class TariffPeriodService {
  private readonly baseUrl = 'http://localhost:8000/api/tariff-periods';

  constructor(private http: HttpClient) {}

  list(): Observable<TariffPeriod[]> {
    return this.http.get<TariffPeriod[]>(this.baseUrl);
  }

  lookups(): Observable<TariffPeriodLookups> {
    return this.http.get<TariffPeriodLookups>(`${this.baseUrl}/lookups`);
  }

  get(id: number): Observable<TariffPeriod> {
    return this.http.get<TariffPeriod>(`${this.baseUrl}/${id}`);
  }

  /** Rejected (409) when the band overlaps another band of the same scope, day type, season and validity. */
  create(payload: TariffPeriodInput): Observable<TariffPeriod> {
    return this.http.post<TariffPeriod>(this.baseUrl, payload);
  }

  update(id: number, payload: TariffPeriodInput): Observable<TariffPeriod> {
    return this.http.put<TariffPeriod>(`${this.baseUrl}/${id}`, payload);
  }

  delete(id: number): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/${id}`);
  }
}
