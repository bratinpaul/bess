import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { CapacityTest, CapacityTestPage, CapacityTestSystem, CapacityTestValues } from '../models/capacity-test.model';

export interface CapacityTestQuery {
  systemId?: number | null;
  start?: string;
  end?: string;
  method?: string;
  sort?: string;
  order?: 'asc' | 'desc';
  page?: number;
  pageSize?: number;
}

/** RUL capacity tests (battery_master.capacity_test): view, edit, delete. */
@Injectable({ providedIn: 'root' })
export class CapacityTestService {
  private readonly baseUrl = 'http://localhost:8000/api/capacity-tests';

  constructor(private http: HttpClient) {}

  systems(): Observable<CapacityTestSystem[]> {
    return this.http.get<CapacityTestSystem[]>(`${this.baseUrl}/systems`);
  }

  methods(): Observable<string[]> {
    return this.http.get<string[]>(`${this.baseUrl}/methods`);
  }

  list(query: CapacityTestQuery = {}): Observable<CapacityTestPage> {
    let params = new HttpParams()
      .set('page', String(query.page ?? 1))
      .set('page_size', String(query.pageSize ?? 50))
      .set('sort', query.sort ?? 'test_date')
      .set('order', query.order ?? 'asc');
    if (query.systemId !== null && query.systemId !== undefined) {
      params = params.set('system_id', String(query.systemId));
    }
    if (query.start) {
      params = params.set('start', query.start);
    }
    if (query.end) {
      params = params.set('end', query.end);
    }
    if (query.method) {
      params = params.set('method', query.method);
    }
    return this.http.get<CapacityTestPage>(this.baseUrl, { params });
  }

  update(testId: number, values: CapacityTestValues): Observable<CapacityTest> {
    return this.http.put<CapacityTest>(`${this.baseUrl}/${testId}`, values);
  }

  delete(testId: number): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/${testId}`);
  }
}
