import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import {
  BulkWeatherForecastResult,
  WeatherForecastCreateInput,
  WeatherForecastInput,
  WeatherForecastLookups,
  WeatherForecastPage,
  WeatherForecastSeries,
  WeatherForecastSkill,
  WeatherForecastValue
} from '../models/weather-forecast.model';

export interface WeatherForecastQuery {
  stationId?: number;
  issuedAt?: string;
  start?: string;
  end?: string;
  page?: number;
  pageSize?: number;
}

/** Weather forecast runs (battery_telemetry.weather_forecast) per weather station. */
@Injectable({ providedIn: 'root' })
export class WeatherForecastService {
  private readonly baseUrl = 'http://localhost:8000/api/weather-forecast';

  constructor(private http: HttpClient) {}

  list(query: WeatherForecastQuery = {}): Observable<WeatherForecastPage> {
    let params = new HttpParams().set('page', String(query.page ?? 1)).set('page_size', String(query.pageSize ?? 25));
    if (query.stationId) {
      params = params.set('station_id', String(query.stationId));
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
    return this.http.get<WeatherForecastPage>(this.baseUrl, { params });
  }

  lookups(): Observable<WeatherForecastLookups> {
    return this.http.get<WeatherForecastLookups>(`${this.baseUrl}/lookups`);
  }

  /** Without issuedAt: the latest run for each hour; with it: that one run. */
  series(stationId: number, issuedAt?: string | null, start?: string, end?: string): Observable<WeatherForecastSeries> {
    let params = new HttpParams().set('station_id', String(stationId));
    if (issuedAt) {
      params = params.set('issued_at', issuedAt);
    }
    if (start) {
      params = params.set('start', start);
    }
    if (end) {
      params = params.set('end', end);
    }
    return this.http.get<WeatherForecastSeries>(`${this.baseUrl}/series`, { params });
  }

  skill(stationId: number, start?: string, end?: string): Observable<WeatherForecastSkill> {
    let params = new HttpParams().set('station_id', String(stationId));
    if (start) {
      params = params.set('start', start);
    }
    if (end) {
      params = params.set('end', end);
    }
    return this.http.get<WeatherForecastSkill>(`${this.baseUrl}/skill`, { params });
  }

  add(payload: WeatherForecastCreateInput): Observable<WeatherForecastValue> {
    return this.http.post<WeatherForecastValue>(this.baseUrl, payload);
  }

  update(stationId: number, issuedAt: string, validAt: string, payload: WeatherForecastInput): Observable<WeatherForecastValue> {
    return this.http.put<WeatherForecastValue>(this.keyUrl(stationId, issuedAt, validAt), payload);
  }

  delete(stationId: number, issuedAt: string, validAt: string): Observable<void> {
    return this.http.delete<void>(this.keyUrl(stationId, issuedAt, validAt));
  }

  /** .csv or .xlsx; without a station_code column the chosen station is used for every row. */
  bulkUpload(file: File, stationCode: string | null): Observable<BulkWeatherForecastResult> {
    const form = new FormData();
    form.append('file', file);
    if (stationCode) {
      form.append('station_code', stationCode);
    }
    return this.http.post<BulkWeatherForecastResult>(`${this.baseUrl}/bulk`, form);
  }

  private keyUrl(stationId: number, issuedAt: string, validAt: string): string {
    return `${this.baseUrl}/${stationId}/${encodeURIComponent(issuedAt)}/${encodeURIComponent(validAt)}`;
  }
}
