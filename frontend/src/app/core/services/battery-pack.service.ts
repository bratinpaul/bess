import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { BatteryPack, BatteryPackInput } from '../models/battery-pack.model';

@Injectable({ providedIn: 'root' })
export class BatteryPackService {
  private readonly baseUrl = 'http://localhost:8000/api/battery-packs';

  constructor(private http: HttpClient) {}

  list(): Observable<BatteryPack[]> {
    return this.http.get<BatteryPack[]>(this.baseUrl);
  }

  get(packId: number): Observable<BatteryPack> {
    return this.http.get<BatteryPack>(`${this.baseUrl}/${packId}`);
  }

  create(payload: BatteryPackInput): Observable<BatteryPack> {
    return this.http.post<BatteryPack>(this.baseUrl, payload);
  }

  update(packId: number, payload: BatteryPackInput): Observable<BatteryPack> {
    return this.http.put<BatteryPack>(`${this.baseUrl}/${packId}`, payload);
  }

  delete(packId: number): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/${packId}`);
  }
}
