import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable, map } from 'rxjs';

import {
  BulkWeatherResult,
  WeatherCreateInput,
  WeatherInput,
  WeatherPage,
  WeatherReading,
  WeatherSeries,
  WeatherStation
} from '../models/weather.model';

export interface WeatherQuery {
  stationId?: number;
  start?: string;
  end?: string;
  page?: number;
  pageSize?: number;
}

/** Measured weather (battery_telemetry.weather_actual) per weather station. */
@Injectable({ providedIn: 'root' })
export class WeatherService {
  private readonly baseUrl = 'http://localhost:8000/api/weather';

  constructor(private http: HttpClient) {}

  list(query: WeatherQuery = {}): Observable<WeatherPage> {
    let params = new HttpParams().set('page', String(query.page ?? 1)).set('page_size', String(query.pageSize ?? 25));
    if (query.stationId) {
      params = params.set('station_id', String(query.stationId));
    }
    if (query.start) {
      params = params.set('start', query.start);
    }
    if (query.end) {
      params = params.set('end', query.end);
    }
    return this.http.get<WeatherPage>(this.baseUrl, { params });
  }

  lookups(): Observable<WeatherStation[]> {
    return this.http.get<{ stations: WeatherStation[] }>(`${this.baseUrl}/lookups`).pipe(map((r) => r.stations));
  }

  series(stationId: number, start?: string, end?: string): Observable<WeatherSeries> {
    let params = new HttpParams().set('station_id', String(stationId));
    if (start) {
      params = params.set('start', start);
    }
    if (end) {
      params = params.set('end', end);
    }
    return this.http.get<WeatherSeries>(`${this.baseUrl}/series`, { params });
  }

  add(payload: WeatherCreateInput): Observable<WeatherReading> {
    return this.http.post<WeatherReading>(this.baseUrl, payload);
  }

  update(stationId: number, ts: string, payload: WeatherInput): Observable<WeatherReading> {
    return this.http.put<WeatherReading>(`${this.baseUrl}/${stationId}/${encodeURIComponent(ts)}`, payload);
  }

  delete(stationId: number, ts: string): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/${stationId}/${encodeURIComponent(ts)}`);
  }

  /** .csv or .xlsx; without a station_code column the chosen station is used for every row. */
  bulkUpload(file: File, stationCode: string | null): Observable<BulkWeatherResult> {
    const form = new FormData();
    form.append('file', file);
    if (stationCode) {
      form.append('station_code', stationCode);
    }
    return this.http.post<BulkWeatherResult>(`${this.baseUrl}/bulk`, form);
  }
}
