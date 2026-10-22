import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { BulkRtPriceResult, RtPrice, RtPriceCreateInput, RtPriceInput, RtPricePage } from '../models/rt-price.model';

export interface RtPriceQuery {
  nodeId?: number | null;
  start?: string;
  end?: string;
  minPrice?: number | null;
  maxPrice?: number | null;
  order?: 'asc' | 'desc';
  page?: number;
  pageSize?: number;
}

/** Real-time / imbalance prices (battery_master.rt_price), keyed by node + interval start.
 *  Price nodes come from DamPriceService.nodes(). */
@Injectable({ providedIn: 'root' })
export class RtPriceService {
  private readonly baseUrl = 'http://localhost:8000/api/rt-prices';

  constructor(private http: HttpClient) {}

  list(query: RtPriceQuery = {}): Observable<RtPricePage> {
    let params = new HttpParams()
      .set('page', String(query.page ?? 1))
      .set('page_size', String(query.pageSize ?? 96))
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
    return this.http.get<RtPricePage>(this.baseUrl, { params });
  }

  add(payload: RtPriceCreateInput): Observable<RtPrice> {
    return this.http.post<RtPrice>(this.baseUrl, payload);
  }

  update(nodeId: number, intervalStart: string, payload: RtPriceInput): Observable<RtPrice> {
    return this.http.put<RtPrice>(this.keyUrl(nodeId, intervalStart), payload);
  }

  delete(nodeId: number, intervalStart: string): Observable<void> {
    return this.http.delete<void>(this.keyUrl(nodeId, intervalStart));
  }

  bulkUpload(file: File, nodeId?: number | null): Observable<BulkRtPriceResult> {
    const form = new FormData();
    form.append('file', file);
    if (nodeId != null) {
      form.append('node_id', String(nodeId));
    }
    return this.http.post<BulkRtPriceResult>(`${this.baseUrl}/bulk`, form);
  }

  /** The interval start carries a +05:30 offset; encode it so the '+' survives the path. */
  private keyUrl(nodeId: number, intervalStart: string): string {
    return `${this.baseUrl}/${nodeId}/${encodeURIComponent(intervalStart)}`;
  }
}
