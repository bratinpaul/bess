import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { Pcs, PcsInput } from '../models/pcs.model';

@Injectable({ providedIn: 'root' })
export class PcsService {
  private readonly baseUrl = 'http://localhost:8000/api/pcs';

  constructor(private http: HttpClient) {}

  list(): Observable<Pcs[]> {
    return this.http.get<Pcs[]>(this.baseUrl);
  }

  get(pcsId: number): Observable<Pcs> {
    return this.http.get<Pcs>(`${this.baseUrl}/${pcsId}`);
  }

  create(payload: PcsInput): Observable<Pcs> {
    return this.http.post<Pcs>(this.baseUrl, payload);
  }

  update(pcsId: number, payload: PcsInput): Observable<Pcs> {
    return this.http.put<Pcs>(`${this.baseUrl}/${pcsId}`, payload);
  }

  delete(pcsId: number): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/${pcsId}`);
  }
}
