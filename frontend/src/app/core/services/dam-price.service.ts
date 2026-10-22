import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import {
  BulkDamPriceResult,
  DamPrice,
  DamPriceCreateInput,
  DamPriceInput,
  DamPricePage,
  PriceNode
} from '../models/dam-price.model';

export interface DamPriceQuery {
  nodeId?: number | null;
  start?: string;
  end?: string;
  minPrice?: number | null;
  maxPrice?: number | null;
  order?: 'asc' | 'desc';
  page?: number;
  pageSize?: number;
}

/** Day-ahead market prices (battery_master.dam_price), keyed by node + delivery start. */
@Injectable({ providedIn: 'root' })
export class DamPriceService {
  private readonly baseUrl = 'http://localhost:8000/api/dam-prices';

  constructor(private http: HttpClient) {}

  nodes(): Observable<PriceNode[]> {
    return this.http.get<PriceNode[]>(`${this.baseUrl}/nodes`);
  }

  list(query: DamPriceQuery = {}): Observable<DamPricePage> {
    let params = new HttpParams()
      .set('page', String(query.page ?? 1))
      .set('page_size', String(query.pageSize ?? 48))
      .set('order', query.order ?? 'asc');
    if (query.nodeId != null) {
      params = params.set('node_id', String(query.nodeId));
    }
    if (query.start) {
      params = params.set('start', query.start);
    }
    if (query.end) {
      params = params.set('end', query.end);
    }
    if (query.minPrice != null) {
      params = params.set('min_price', String(query.minPrice));
    }
    if (query.maxPrice != null) {
      params = params.set('max_price', String(query.maxPrice));
    }
    return this.http.get<DamPricePage>(this.baseUrl, { params });
  }

  add(payload: DamPriceCreateInput): Observable<DamPrice> {
    return this.http.post<DamPrice>(this.baseUrl, payload);
  }

  update(nodeId: number, deliveryStart: string, payload: DamPriceInput): Observable<DamPrice> {
    return this.http.put<DamPrice>(this.keyUrl(nodeId, deliveryStart), payload);
  }

  delete(nodeId: number, deliveryStart: string): Observable<void> {
    return this.http.delete<void>(this.keyUrl(nodeId, deliveryStart));
  }

  bulkUpload(file: File, nodeId?: number | null): Observable<BulkDamPriceResult> {
    const form = new FormData();
    form.append('file', file);
    if (nodeId != null) {
      form.append('node_id', String(nodeId));
    }
    return this.http.post<BulkDamPriceResult>(`${this.baseUrl}/bulk`, form);
  }

  /** The delivery start carries a +05:30 offset; encode it so the '+' survives the path. */
  private keyUrl(nodeId: number, deliveryStart: string): string {
    return `${this.baseUrl}/${nodeId}/${encodeURIComponent(deliveryStart)}`;
  }
}
