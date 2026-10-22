import { CommonModule } from '@angular/common';
import { Component, OnDestroy, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';

import {
  BatchLog,
  BatchLogPage,
  BatchRunResult,
  BatchStatus,
  BatchStatusValue,
  InboxFile
} from '../../../core/models/batch.model';
import { BatchService } from '../../../core/services/batch.service';

const REFRESH_MS = 15_000;
const PAGE_SIZE = 25;

@Component({
  selector: 'app-realtime-batch',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './realtime-batch.component.html',
  styleUrl: './realtime-batch.component.scss'
})
export class RealtimeBatchComponent implements OnInit, OnDestroy {
  status: BatchStatus | null = null;
  statusError: string | null = null;

  // manual run
  running = false;
  runResult: BatchRunResult | null = null;
  runError: string | null = null;
  showOutput = false;

  // history (battery_raw.batchlog)
  logs: BatchLogPage | null = null;
  logsLoading = true;
  logsError: string | null = null;
  statusFilter: BatchStatusValue | '' = '';
  search = '';
  offset = 0;
  readonly pageSize = PAGE_SIZE;
  expanded: number | null = null;
  readonly statuses: BatchStatusValue[] = ['SUCCESS', 'PARTIAL', 'FAILED'];

  private timer?: ReturnType<typeof setInterval>;
  private searchTimer?: ReturnType<typeof setTimeout>;
  private lastSeenBatchId: number | null = null;

  constructor(private service: BatchService) {}

  ngOnInit(): void {
    this.loadStatus();
    this.loadLogs();
    // keep the inbox, schedule and history current while the page is open (scheduled runs happen every minute)
    this.timer = setInterval(() => this.loadStatus(true), REFRESH_MS);
  }

  ngOnDestroy(): void {
    clearInterval(this.timer);
    clearTimeout(this.searchTimer);
  }

  // ---------------------------------------------------------------- status

  loadStatus(background = false): void {
    this.service.status().subscribe({
      next: (status) => {
        this.status = status;
        this.statusError = null;
        // a scheduled run logged something new: refresh the history if it's showing the newest rows
        const newest = status.last_run?.batch_id ?? null;
        if (background && newest !== this.lastSeenBatchId && this.offset === 0 && !this.running) {
          this.loadLogs(true);
        }
        this.lastSeenBatchId = newest;
      },
      error: () => {
        if (!background || !this.status) {
          this.statusError = 'Could not load the batch status. Is the backend running?';
        }
      }
    });
  }

  get waiting(): InboxFile[] {
    return this.status?.files.filter((f) => f.valid_name) ?? [];
  }

  get ignored(): InboxFile[] {
    return this.status?.files.filter((f) => !f.valid_name) ?? [];
  }

  get readyCount(): number {
    return this.waiting.filter((f) => f.ready).length;
  }

  // ---------------------------------------------------------------- run now

  runNow(): void {
    if (this.running) {
      return;
    }
    this.running = true;
    this.runError = null;
    this.runResult = null;
    this.showOutput = false;
    this.service.run().subscribe({
      next: (result) => {
        this.runResult = result;
        this.running = false;
        this.loadStatus();
        this.offset = 0;
        this.loadLogs();
      },
      error: (err) => {
        this.runError = err?.error?.detail || 'The batch could not be started. Is the backend running?';
        this.running = false;
        this.loadStatus();
      }
    });
  }

  get runSummary(): { inserted: number; updated: number; skipped: number } {
    const runs = this.runResult?.runs ?? [];
    return {
      inserted: runs.reduce((s, r) => s + r.rows_inserted, 0),
      updated: runs.reduce((s, r) => s + r.rows_updated, 0),
      skipped: runs.reduce((s, r) => s + r.rows_skipped, 0)
    };
  }

  /** Output lines without the log timestamp prefix ("2026-09-28 22:08:50 INFO    ..."). */
  get outputLines(): string[] {
    return (this.runResult?.output ?? []).map((line) => line.replace(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} /, ''));
  }

  // ---------------------------------------------------------------- history

  loadLogs(background = false): void {
    if (!background) {
      this.logsLoading = true;
    }
    this.service
      .logs({ status: this.statusFilter, q: this.search, limit: this.pageSize, offset: this.offset })
      .subscribe({
        next: (page) => {
          this.logs = page;
          this.logsLoading = false;
          this.logsError = null;
        },
        error: () => {
          this.logsError = 'Could not load the batch log.';
          this.logsLoading = false;
        }
      });
  }

  setStatusFilter(status: BatchStatusValue | ''): void {
    this.statusFilter = status;
    this.offset = 0;
    this.expanded = null;
    this.loadLogs();
  }

  onSearchChange(): void {
    clearTimeout(this.searchTimer);
    this.searchTimer = setTimeout(() => {
      this.offset = 0;
      this.loadLogs();
    }, 300);
  }

  get allCount(): number {
    const c = this.logs?.counts;
    return c ? c.SUCCESS + c.PARTIAL + c.FAILED : 0;
  }

  get rangeLabel(): string {
    const total = this.logs?.total ?? 0;
    return total === 0 ? '0' : `${this.offset + 1}–${Math.min(this.offset + this.pageSize, total)} of ${total}`;
  }

  page(delta: number): void {
    const next = this.offset + delta * this.pageSize;
    if (next >= 0 && next < (this.logs?.total ?? 0)) {
      this.offset = next;
      this.expanded = null;
      this.loadLogs();
    }
  }

  toggle(log: BatchLog): void {
    this.expanded = this.expanded === log.batch_id ? null : log.batch_id;
  }

  // ---------------------------------------------------------------- display

  plantTime(iso: string | null | undefined): string {
    return iso ? iso.slice(0, 19).replace('T', ' ') : '—';
  }

  duration(ms: number): string {
    return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
  }

  size(bytes: number): string {
    return bytes < 1024 ? `${bytes} B` : `${(bytes / 1024).toFixed(1)} KB`;
  }
}
