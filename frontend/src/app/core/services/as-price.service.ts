import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import {
  AsPrice,
  AsPriceCreateInput,
  AsPriceInput,
  AsPricePage,
  AsProduct,
  BulkAsPriceResult
} from '../models/as-price.model';

export interface AsPriceQuery {
  productId?: number | null;
  start?: string;
  end?: string;
  minCapacity?: number | null;
  maxCapacity?: number | null;
  order?: 'asc' | 'desc';
  page?: number;
  pageSize?: number;
}

/** Ancillary-service prices (battery_master.as_price), keyed by product + delivery start. */
@Injectable({ providedIn: 'root' })
export class AsPriceService {
  private readonly baseUrl = 'http://localhost:8000/api/as-prices';

  constructor(private http: HttpClient) {}

  products(): Observable<AsProduct[]> {
    return this.http.get<AsProduct[]>(`${this.baseUrl}/products`);
  }

  list(query: AsPriceQuery = {}): Observable<AsPricePage> {
    let params = new HttpParams()
      .set('page', String(query.page ?? 1))
      .set('page_size', String(query.pageSize ?? 48))
      .set('order', query.order ?? 'asc');
    if (query.productId != null) {
      params = params.set('product_id', String(query.productId));
    }
    if (query.start) {
      params = params.set('start', query.start);
    }
    if (query.end) {
      params = params.set('end', query.end);
    }
    if (query.minCapacity != null) {
      params = params.set('min_capacity', String(query.minCapacity));
    }
    if (query.maxCapacity != null) {
      params = params.set('max_capacity', String(query.maxCapacity));
    }
    return this.http.get<AsPricePage>(this.baseUrl, { params });
  }

  add(payload: AsPriceCreateInput): Observable<AsPrice> {
    return this.http.post<AsPrice>(this.baseUrl, payload);
  }

  update(productId: number, deliveryStart: string, payload: AsPriceInput): Observable<AsPrice> {
    return this.http.put<AsPrice>(this.keyUrl(productId, deliveryStart), payload);
  }

  delete(productId: number, deliveryStart: string): Observable<void> {
    return this.http.delete<void>(this.keyUrl(productId, deliveryStart));
  }

  bulkUpload(file: File, productId?: number | null): Observable<BulkAsPriceResult> {
    const form = new FormData();
    form.append('file', file);
    if (productId != null) {
      form.append('product_id', String(productId));
    }
    return this.http.post<BulkAsPriceResult>(`${this.baseUrl}/bulk`, form);
  }

  /** The delivery start carries a +05:30 offset; encode it so the '+' survives the path. */
  private keyUrl(productId: number, deliveryStart: string): string {
    return `${this.baseUrl}/${productId}/${encodeURIComponent(deliveryStart)}`;
  }
}
