import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { SocRefOptions, SocReference, SocReferenceValues } from '../models/soc-reference.model';

export interface SocRefQuery {
  systemId?: number | null;
  method?: string;
  start?: string;
  end?: string;
}

/** SOC reference points (battery_master.soc_reference): view, edit, delete. */
@Injectable({ providedIn: 'root' })
export class SocReferenceService {
  private readonly baseUrl = 'http://localhost:8000/api/soc-reference';

  constructor(private http: HttpClient) {}

  options(): Observable<SocRefOptions> {
    return this.http.get<SocRefOptions>(`${this.baseUrl}/options`);
  }

  list(q: SocRefQuery = {}): Observable<SocReference[]> {
    let params = new HttpParams();
    if (q.systemId !== null && q.systemId !== undefined) {
      params = params.set('system_id', String(q.systemId));
    }
    if (q.method) {
      params = params.set('method', q.method);
    }
    if (q.start) {
      params = params.set('start', q.start);
    }
    if (q.end) {
      params = params.set('end', q.end);
    }
    return this.http.get<SocReference[]>(this.baseUrl, { params });
  }

  /** The key timestamp goes into the URL encoded (its '+05:30' offset would otherwise read as a space). */
  private url(r: SocReference): string {
    return `${this.baseUrl}/${r.system_id}/${encodeURIComponent(r.ts)}`;
  }

  update(r: SocReference, values: SocReferenceValues): Observable<SocReference> {
    return this.http.put<SocReference>(this.url(r), values);
  }

  delete(r: SocReference): Observable<void> {
    return this.http.delete<void>(this.url(r));
  }
}
