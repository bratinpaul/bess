import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { OperationsOverview } from '../models/operations.model';

@Injectable({ providedIn: 'root' })
export class OperationsService {
  private readonly baseUrl = 'http://localhost:8000/api/operations';

  constructor(private http: HttpClient) {}

  overview(systemId: number, days: number): Observable<OperationsOverview> {
    const params = new HttpParams().set('system_id', systemId).set('days', String(days));
    return this.http.get<OperationsOverview>(`${this.baseUrl}/overview`, { params });
  }
}
