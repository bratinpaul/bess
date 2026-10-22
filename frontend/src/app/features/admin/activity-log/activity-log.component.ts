import { CommonModule } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { Component, OnInit, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute } from '@angular/router';

import { BACKEND_URL } from '../../../core/auth/auth.config';

interface ActivityRow {
  activity_id: number;
  ts: string;
  service: string;
  kind: string;
  event: string;
  outcome: 'success' | 'failed';
  request_id: string | null;
  user_email: string | null;
  role: string | null;
  method: string | null;
  path: string | null;
  status_code: number | null;
  duration_ms: number | null;
  operation: string | null;
  rows_total: number | null;
  rows_inserted: number | null;
  rows_updated: number | null;
  rows_rejected: number | null;
  ip: string | null;
  detail: Record<string, unknown> | null;
}

interface ActivityPage {
  items: ActivityRow[];
  total: number;
  page: number;
  page_size: number;
  counts: { kind: string; outcome: string; n: number }[];
}

const KINDS = ['REQUEST', 'AUTH', 'LOAD', 'KPI', 'TRAINING', 'ERROR'];

/** Administration -> Activity Log: user actions, failed requests, loads (with row counts), KPI runs, training and auth
 *  events from battery_itops.activity_log - searchable by the request id users see on error banners. */
@Component({
  selector: 'app-activity-log',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './activity-log.component.html',
  styleUrl: './activity-log.component.scss'
})
export class ActivityLogComponent implements OnInit {
  private http = inject(HttpClient);
  private route = inject(ActivatedRoute);
  private readonly base = `${BACKEND_URL}/api/admin/activity`;

  readonly kinds = KINDS;
  services: string[] = [];
  f = { kind: '', outcome: '', service: '', user: '', request_id: '', q: '', date_from: '', date_to: '' };
  page = 1;
  pageSize = 50;
  data: ActivityPage | null = null;
  loading = false;
  error: string | null = null;
  open: number | null = null;

  ngOnInit(): void {
    const rid = this.route.snapshot.queryParamMap.get('request_id');
    if (rid) {
      this.f.request_id = rid;
    }
    this.http.get<{ services: string[] }>(`${this.base}/lookups`).subscribe({ next: (l) => (this.services = l.services) });
    this.load();
  }

  load(page = 1): void {
    this.page = page;
    this.loading = true;
    this.error = null;
    const params: Record<string, string | number> = { page, page_size: this.pageSize };
    for (const [k, v] of Object.entries(this.f)) {
      if (v && String(v).trim()) {
        params[k] = String(v).trim();
      }
    }
    this.http.get<ActivityPage>(this.base, { params }).subscribe({
      next: (d) => {
        this.loading = false;
        this.data = d;
      },
      error: (err) => {
        this.loading = false;
        this.error = err?.status === 0 ? 'Cannot reach the server (port 8000).' : 'Could not load the activity log.';
      }
    });
  }

  reset(): void {
    this.f = { kind: '', outcome: '', service: '', user: '', request_id: '', q: '', date_from: '', date_to: '' };
    this.load();
  }

  byRequest(rid: string | null): void {
    if (rid) {
      this.f = { ...this.f, request_id: rid, kind: '', outcome: '' };
      this.load();
    }
  }

  count(kind: string, outcome?: string): number {
    return (this.data?.counts ?? []).filter((c) => c.kind === kind && (!outcome || c.outcome === outcome))
      .reduce((a, c) => a + c.n, 0);
  }

  get pages(): number {
    return this.data ? Math.max(1, Math.ceil(this.data.total / this.data.page_size)) : 1;
  }

  rows(r: ActivityRow): string {
    if (r.rows_total == null && r.rows_inserted == null) {
      return '';
    }
    const parts = [];
    if (r.rows_total != null) parts.push(`${r.rows_total} rows`);
    if (r.rows_inserted) parts.push(`+${r.rows_inserted}`);
    if (r.rows_updated) parts.push(`~${r.rows_updated}`);
    if (r.rows_rejected) parts.push(`✕${r.rows_rejected}`);
    return parts.join(' · ');
  }

  detail(r: ActivityRow): string {
    return r.detail ? JSON.stringify(r.detail, null, 2) : '';
  }

  ms(v: number | null): string {
    if (v == null) return '';
    return v >= 1000 ? `${(v / 1000).toFixed(1)} s` : `${v} ms`;
  }
}
