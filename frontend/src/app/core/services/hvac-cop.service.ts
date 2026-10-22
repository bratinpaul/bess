import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { CopOptions, CopPoint, CopPrediction, CopRun, CopRunRequest } from '../models/hvac-cop.model';

/** HVAC COP & cooling-performance use case of the ML service (/hvac-cop). */
@Injectable({ providedIn: 'root' })
export class HvacCopService {
  private readonly baseUrl = 'http://localhost:8100/hvac-cop';

  constructor(private http: HttpClient) {}

  options(): Observable<CopOptions> {
    return this.http.get<CopOptions>(`${this.baseUrl}/options`);
  }

  /** Fits the maps and builds the scorecard for every unit (about 3 s each); resolves with the stored run. */
  createRun(body: CopRunRequest): Observable<CopRun> {
    return this.http.post<CopRun>(`${this.baseUrl}/runs`, body);
  }

  runs(): Observable<CopRun[]> {
    return this.http.get<CopRun[]>(`${this.baseUrl}/runs`);
  }

  run(id: number): Observable<CopRun> {
    return this.http.get<CopRun>(`${this.baseUrl}/runs/${id}`);
  }

  deleteRun(id: number): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/runs/${id}`);
  }

  points(id: number, hvacId: number, dayFrom: string, dayTo?: string): Observable<CopPoint[]> {
    let params = new HttpParams().set('hvac_id', hvacId).set('day_from', dayFrom);
    if (dayTo) {
      params = params.set('day_to', dayTo);
    }
    return this.http.get<CopPoint[]>(`${this.baseUrl}/runs/${id}/points`, { params });
  }

  predict(body: { run_id: number; hvac_id: number; ambient_c: number; supply_c: number; plr?: number | null; heat_load_kw?: number | null }): Observable<CopPrediction> {
    return this.http.post<CopPrediction>(`${this.baseUrl}/predict`, body);
  }
}
