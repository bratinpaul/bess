import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { BatteryProvenance, BatteryProvenanceValues, ProvenanceOptions } from '../models/battery-provenance.model';

export interface ProvenanceQuery {
  chemistry?: string;
  batchLot?: string;
  sort?: string;
  order?: 'asc' | 'desc';
}

/** RUL battery provenance (battery_master.battery_provenance): view, edit, delete. */
@Injectable({ providedIn: 'root' })
export class BatteryProvenanceService {
  private readonly baseUrl = 'http://localhost:8000/api/battery-provenance';

  constructor(private http: HttpClient) {}

  options(): Observable<ProvenanceOptions> {
    return this.http.get<ProvenanceOptions>(`${this.baseUrl}/options`);
  }

  list(query: ProvenanceQuery = {}): Observable<BatteryProvenance[]> {
    let params = new HttpParams().set('sort', query.sort ?? 'system_code').set('order', query.order ?? 'asc');
    if (query.chemistry) {
      params = params.set('chemistry', query.chemistry);
    }
    if (query.batchLot) {
      params = params.set('batch_lot', query.batchLot);
    }
    return this.http.get<BatteryProvenance[]>(this.baseUrl, { params });
  }

  update(systemId: number, values: BatteryProvenanceValues): Observable<BatteryProvenance> {
    return this.http.put<BatteryProvenance>(`${this.baseUrl}/${systemId}`, values);
  }

  delete(systemId: number): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/${systemId}`);
  }
}
