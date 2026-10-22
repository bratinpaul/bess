import { CommonModule } from '@angular/common';
import { Component, OnDestroy, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';

import {
  BatchLog,
  BatchLogPage,
  BatchRunResult,
  BatchStatusValue,
  StaticBatchStatus
} from '../../../core/models/batch.model';
import { BatchService } from '../../../core/services/batch.service';

const REFRESH_MS = 15_000;
const PAGE_SIZE = 25;

/** Batch -> Static Data Load: load the master data JSON in input/static and show its batch log. */
@Component({
  selector: 'app-static-batch',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './static-batch.component.html',
  styleUrl: '../realtime-batch/realtime-batch.component.scss'
})
export class StaticBatchComponent implements OnInit, OnDestroy {
  status: StaticBatchStatus | null = null;
  statusError: string | null = null;

  running = false;
  runResult: BatchRunResult | null = null;
  runError: string | null = null;
  showOutput = false;

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
  private logsSeq = 0;

  constructor(private service: BatchService) {}

  ngOnInit(): void {
    this.loadStatus();
    this.loadLogs();
    this.timer = setInterval(() => this.loadStatus(true), REFRESH_MS);
  }

  ngOnDestroy(): void {
    clearInterval(this.timer);
    clearTimeout(this.searchTimer);
  }

  // ---------------------------------------------------------------- status

  loadStatus(background = false): void {
    this.service.staticStatus().subscribe({
      next: (status) => {
        this.status = status;
        this.statusError = null;
      },
      error: () => {
        if (!background || !this.status) {
          this.statusError = 'Could not load the batch status. Is the backend running?';
        }
      }
    });
  }

  get readyCount(): number {
    return this.status?.files.filter((f) => f.ready).length ?? 0;
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
    this.service.runStatic().subscribe({
      next: (result) => {
        this.runResult = result;
        this.running = false;
        this.loadStatus();
        this.offset = 0;
        this.expanded = result.runs.length === 1 ? result.runs[0].batch_id : null;
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

  get outputLines(): string[] {
    return (this.runResult?.output ?? []).map((line) => line.replace(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} /, ''));
  }

  // ---------------------------------------------------------------- batch log

  loadLogs(): void {
    const seq = ++this.logsSeq;
    this.logsLoading = true;
    this.service
      .staticLogs({ status: this.statusFilter, q: this.search, limit: this.pageSize, offset: this.offset })
      .subscribe({
        next: (page) => {
          if (seq !== this.logsSeq) {
            return;
          }
          this.logs = page;
          this.logsLoading = false;
          this.logsError = null;
        },
        error: () => {
          if (seq !== this.logsSeq) {
            return;
          }
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
    return bytes < 1024 ? `${bytes} B` : bytes < 1024 * 1024 ? `${(bytes / 1024).toFixed(1)} KB` : `${(bytes / 1048576).toFixed(1)} MB`;
  }
}
