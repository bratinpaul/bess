import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { BatterySystem, BatterySystemInput } from '../models/battery-system.model';

@Injectable({ providedIn: 'root' })
export class BatterySystemService {
  private readonly baseUrl = 'http://localhost:8000/api/battery-systems';

  constructor(private http: HttpClient) {}

  list(): Observable<BatterySystem[]> {
    return this.http.get<BatterySystem[]>(this.baseUrl);
  }

  get(batterySystemId: number): Observable<BatterySystem> {
    return this.http.get<BatterySystem>(`${this.baseUrl}/${batterySystemId}`);
  }

  create(payload: BatterySystemInput): Observable<BatterySystem> {
    return this.http.post<BatterySystem>(this.baseUrl, payload);
  }

  update(batterySystemId: number, payload: BatterySystemInput): Observable<BatterySystem> {
    return this.http.put<BatterySystem>(`${this.baseUrl}/${batterySystemId}`, payload);
  }

  delete(batterySystemId: number): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/${batterySystemId}`);
  }
}
