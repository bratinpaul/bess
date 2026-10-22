import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { CalSystem, CurrentSensorCal, CurrentSensorCalValues } from '../models/current-sensor-cal.model';

/** Current-sensor calibrations (battery_master.current_sensor_cal): view, edit, delete. */
@Injectable({ providedIn: 'root' })
export class CurrentSensorCalService {
  private readonly baseUrl = 'http://localhost:8000/api/current-sensor-cal';

  constructor(private http: HttpClient) {}

  systems(): Observable<CalSystem[]> {
    return this.http.get<CalSystem[]>(`${this.baseUrl}/systems`);
  }

  list(systemId: number | null, start?: string, end?: string): Observable<CurrentSensorCal[]> {
    let params = new HttpParams();
    if (systemId !== null) {
      params = params.set('system_id', String(systemId));
    }
    if (start) {
      params = params.set('start', start);
    }
    if (end) {
      params = params.set('end', end);
    }
    return this.http.get<CurrentSensorCal[]>(this.baseUrl, { params });
  }

  update(c: CurrentSensorCal, values: CurrentSensorCalValues): Observable<CurrentSensorCal> {
    return this.http.put<CurrentSensorCal>(`${this.baseUrl}/${c.system_id}/${c.calibrated_on}`, values);
  }

  delete(c: CurrentSensorCal): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/${c.system_id}/${c.calibrated_on}`);
  }
}
