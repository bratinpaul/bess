import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import {
  BulkPriceForecastResult,
  ForecastVintage,
  PriceForecast,
  PriceForecastCreateInput,
  PriceForecastInput,
  PriceForecastPage
} from '../models/market-price-forecast.model';

export interface PriceForecastQuery {
  nodeId?: number | null;
  /** ISO issue time of one vintage. */
  issuedAt?: string | null;
  start?: string;
  end?: string;
  model?: string | null;
  order?: 'asc' | 'desc';
  page?: number;
  pageSize?: number;
}

/** Probabilistic price forecasts (battery_master.price_forecast), keyed by node + issued_at + target_ts.
 *  Price nodes come from DamPriceService.nodes(). */
@Injectable({ providedIn: 'root' })
export class MarketPriceForecastService {
  private readonly baseUrl = 'http://localhost:8000/api/price-forecasts';

  constructor(private http: HttpClient) {}

  vintages(nodeId?: number | null): Observable<ForecastVintage[]> {
    let params = new HttpParams();
    if (nodeId != null) {
      params = params.set('node_id', String(nodeId));
    }
    return this.http.get<ForecastVintage[]>(`${this.baseUrl}/vintages`, { params });
  }

  models(): Observable<string[]> {
    return this.http.get<string[]>(`${this.baseUrl}/models`);
  }

  list(query: PriceForecastQuery = {}): Observable<PriceForecastPage> {
    let params = new HttpParams()
      .set('page', String(query.page ?? 1))
      .set('page_size', String(query.pageSize ?? 48))
      .set('order', query.order ?? 'asc');
    if (query.nodeId != null) {
      params = params.set('node_id', String(query.nodeId));
    }
    if (query.issuedAt) {
      params = params.set('issued_at', query.issuedAt);
    }
    if (query.start) {
      params = params.set('start', query.start);
    }
    if (query.end) {
      params = params.set('end', query.end);
    }
    if (query.model) {
      params = params.set('model', query.model);
    }
    return this.http.get<PriceForecastPage>(this.baseUrl, { params });
  }

  add(payload: PriceForecastCreateInput): Observable<PriceForecast> {
    return this.http.post<PriceForecast>(this.baseUrl, payload);
  }

  update(nodeId: number, issuedAt: string, targetTs: string, payload: PriceForecastInput): Observable<PriceForecast> {
    return this.http.put<PriceForecast>(this.keyUrl(nodeId, issuedAt, targetTs), payload);
  }

  delete(nodeId: number, issuedAt: string, targetTs: string): Observable<void> {
    return this.http.delete<void>(this.keyUrl(nodeId, issuedAt, targetTs));
  }

  bulkUpload(file: File, nodeId?: number | null): Observable<BulkPriceForecastResult> {
    const form = new FormData();
    form.append('file', file);
    if (nodeId != null) {
      form.append('node_id', String(nodeId));
    }
    return this.http.post<BulkPriceForecastResult>(`${this.baseUrl}/bulk`, form);
  }

  /** The timestamps carry a +05:30 offset; encode them so the '+' survives the path. */
  private keyUrl(nodeId: number, issuedAt: string, targetTs: string): string {
    return `${this.baseUrl}/${nodeId}/${encodeURIComponent(issuedAt)}/${encodeURIComponent(targetTs)}`;
  }
}
