import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { BatteryContainer, BatteryContainerInput } from '../models/battery-container.model';

@Injectable({ providedIn: 'root' })
export class BatteryContainerService {
  private readonly baseUrl = 'http://localhost:8000/api/battery-containers';

  constructor(private http: HttpClient) {}

  list(): Observable<BatteryContainer[]> {
    return this.http.get<BatteryContainer[]>(this.baseUrl);
  }

  get(containerId: number): Observable<BatteryContainer> {
    return this.http.get<BatteryContainer>(`${this.baseUrl}/${containerId}`);
  }

  create(payload: BatteryContainerInput): Observable<BatteryContainer> {
    return this.http.post<BatteryContainer>(this.baseUrl, payload);
  }

  update(containerId: number, payload: BatteryContainerInput): Observable<BatteryContainer> {
    return this.http.put<BatteryContainer>(`${this.baseUrl}/${containerId}`, payload);
  }

  delete(containerId: number): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/${containerId}`);
  }
}
