import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { BatteryModule, BatteryModuleInput } from '../models/battery-module.model';

@Injectable({ providedIn: 'root' })
export class BatteryModuleService {
  private readonly baseUrl = 'http://localhost:8000/api/battery-modules';

  constructor(private http: HttpClient) {}

  list(): Observable<BatteryModule[]> {
    return this.http.get<BatteryModule[]>(this.baseUrl);
  }

  get(moduleId: number): Observable<BatteryModule> {
    return this.http.get<BatteryModule>(`${this.baseUrl}/${moduleId}`);
  }

  create(payload: BatteryModuleInput): Observable<BatteryModule> {
    return this.http.post<BatteryModule>(this.baseUrl, payload);
  }

  update(moduleId: number, payload: BatteryModuleInput): Observable<BatteryModule> {
    return this.http.put<BatteryModule>(`${this.baseUrl}/${moduleId}`, payload);
  }

  delete(moduleId: number): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/${moduleId}`);
  }
}
