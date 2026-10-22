import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { EmsController, EmsControllerInput } from '../models/ems-controller.model';

@Injectable({ providedIn: 'root' })
export class EmsControllerService {
  private readonly baseUrl = 'http://localhost:8000/api/ems-controllers';

  constructor(private http: HttpClient) {}

  list(): Observable<EmsController[]> {
    return this.http.get<EmsController[]>(this.baseUrl);
  }

  get(id: number): Observable<EmsController> {
    return this.http.get<EmsController>(`${this.baseUrl}/${id}`);
  }

  create(payload: EmsControllerInput): Observable<EmsController> {
    return this.http.post<EmsController>(this.baseUrl, payload);
  }

  update(id: number, payload: EmsControllerInput): Observable<EmsController> {
    return this.http.put<EmsController>(`${this.baseUrl}/${id}`, payload);
  }

  /** Refused (409) while telemetry is recorded against it. */
  delete(id: number): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/${id}`);
  }
}
