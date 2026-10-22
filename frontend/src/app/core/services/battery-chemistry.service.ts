import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { BatteryChemistry } from '../models/battery-system.model';

@Injectable({ providedIn: 'root' })
export class BatteryChemistryService {
  private readonly baseUrl = 'http://localhost:8000/api/battery-chemistries';

  constructor(private http: HttpClient) {}

  list(): Observable<BatteryChemistry[]> {
    return this.http.get<BatteryChemistry[]>(this.baseUrl);
  }
}
