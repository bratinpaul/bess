import { CommonModule } from '@angular/common';
import { Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';

import {
  BatchLog,
  BatchLogPage,
  BatchStatusValue,
  HistoricalFeed,
  HistoricalLoadRequest,
  HistoricalOptions,
  HistoricalScan,
  HistoricalSite,
  HistoricalStatus,
  HistoricalSystem
} from '../../../core/models/batch.model';
import { BatchService } from '../../../core/services/batch.service';

const PAGE_SIZE = 15;

/**
 * Batch -> Historical Load: load a folder of historical telemetry files for any site / battery system.
 * Steps: 1 choose the site, system and folder (master data) - 2 check the files - 3 include / exclude files -
 * 4 start the load - 5 monitor it by hand (Refresh status). Nothing runs or refreshes on its own.
 */
@Component({
  selector: 'app-historical-load',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './historical-load.component.html',
  styleUrls: ['../realtime-batch/realtime-batch.component.scss', './historical-load.component.scss']
})
export class HistoricalLoadComponent implements OnInit {
  options: HistoricalOptions | null = null;
  optionsError: string | null = null;

  // inputs
  siteId: number | null = null;
  systemName = '';
  folder = '';
  recursive = true;
  feeds = new Set<HistoricalFeed>();
  emsCode: string | null = null;
  hvacCode: string | null = null;

  // scan (preview) and the files the user includes
  scan: HistoricalScan | null = null;
  included = new Set<string>();
  scanning = false;
  scanError: string | null = null;

  // run (monitored by hand)
  status: HistoricalStatus | null = null;
  starting = false;
  runError: string | null = null;
  refreshing = false;
  refreshedAt: Date | null = null;

  // batch log
  logs: BatchLogPage | null = null;
  logsLoading = true;
  statusFilter: BatchStatusValue | '' = '';
  offset = 0;
  readonly pageSize = PAGE_SIZE;
  expanded: number | null = null;
  readonly statuses: BatchStatusValue[] = ['SUCCESS', 'PARTIAL', 'FAILED'];

  constructor(private service: BatchService) {}

  ngOnInit(): void {
    this.service.historicalOptions().subscribe({
      next: (options) => {
        this.options = options;
        this.feeds = new Set(options.feeds.map((f) => f.key));
        this.folder = options.folders.find((f) => f.path.toLowerCase().startsWith('historical'))?.path ?? '';
      },
      error: () => (this.optionsError = 'Could not load the sites. Is the backend running?')
    });
    this.refresh();
  }

  // ---------------------------------------------------------------- inputs

  get site(): HistoricalSite | undefined {
    return this.options?.sites.find((s) => s.site_id === this.siteId);
  }

  get system(): HistoricalSystem | undefined {
    return this.site?.systems.find((s) => s.system_name === this.systemName);
  }

  onSiteChange(): void {
    const systems = this.site?.systems ?? [];
    this.systemName = systems.length === 1 ? systems[0].system_name : '';
    this.onSystemChange();
  }

  onSystemChange(): void {
    this.emsCode = this.system?.ems_codes.length === 1 ? this.system.ems_codes[0] : null;
    this.hvacCode = this.system?.hvac_codes.length === 1 ? this.system.hvac_codes[0] : null;
    this.resetScan();
  }

  toggleFeed(key: HistoricalFeed): void {
    this.feeds.has(key) ? this.feeds.delete(key) : this.feeds.add(key);
    this.feeds = new Set(this.feeds);
    this.resetScan();
  }

  resetScan(): void {
    this.scan = null;
    this.scanError = null;
    this.included = new Set();
  }

  get request(): HistoricalLoadRequest {
    return {
      system_name: this.systemName,
      folder: this.folder,
      feeds: Array.from(this.feeds),
      recursive: this.recursive,
      ems_code: this.emsCode,
      hvac_code: this.hvacCode
    };
  }

  get ready(): boolean {
    return !!this.systemName && !!this.folder && this.feeds.size > 0;
  }

  // ---------------------------------------------------------------- scan

  runScan(): void {
    if (!this.ready) {
      return;
    }
    this.scanning = true;
    this.scanError = null;
    this.service.historicalScan(this.request).subscribe({
      next: (scan) => {
        this.scan = scan;
        this.scanning = false;
        // every file that passed the check is included to start with
        this.included = new Set(scan.feeds.flatMap((f) => f.files.filter((x) => x.selected && x.ok).map((x) => x.name)));
      },
      error: (err) => {
        this.scanError = err?.error?.detail || 'Could not scan the folder.';
        this.scanning = false;
      }
    });
  }

  get loadable(): number {
    return this.included.size;
  }

  isIncluded(name: string): boolean {
    return this.included.has(name);
  }

  toggleFile(name: string): void {
    this.included.has(name) ? this.included.delete(name) : this.included.add(name);
    this.included = new Set(this.included);
  }

  /** Include / exclude every checked file of one feed (or of all feeds). */
  setAll(include: boolean, feedKey?: HistoricalFeed): void {
    const names = (this.scan?.feeds ?? [])
      .filter((f) => !feedKey || f.key === feedKey)
      .flatMap((f) => f.files.filter((x) => x.selected && x.ok).map((x) => x.name));
    names.forEach((n) => (include ? this.included.add(n) : this.included.delete(n)));
    this.included = new Set(this.included);
  }

  fileTitle(file: { ok: boolean; message: string | null; name: string }): string {
    if (!file.ok) {
      return `Can't be loaded: ${file.message}`;
    }
    return this.included.has(file.name) ? 'Included - click to exclude' : 'Excluded - click to include';
  }

  feedIncluded(key: HistoricalFeed): number {
    return (this.scan?.feeds.find((f) => f.key === key)?.files ?? []).filter((x) => this.included.has(x.name)).length;
  }

  get checkable(): number {
    return (this.scan?.feeds ?? []).reduce((n, f) => n + f.files.filter((x) => x.selected && x.ok).length, 0);
  }

  get blocked(): number {
    return (this.scan?.feeds ?? []).reduce((n, f) => n + f.files.filter((x) => x.selected && !x.ok).length, 0);
  }

  feedSelected(key: HistoricalFeed): boolean {
    return this.feeds.has(key);
  }

  // ---------------------------------------------------------------- run

  start(): void {
    if (!this.scan || this.running || this.loadable === 0 || this.scan.problems.length) {
      return;
    }
    this.starting = true;
    this.runError = null;
    this.service.historicalRun({ ...this.request, files: Array.from(this.included) }).subscribe({
      next: (status) => {
        this.status = status;
        this.refreshedAt = new Date();
        this.starting = false;
      },
      error: (err) => {
        this.runError = err?.error?.detail || 'The load could not be started.';
        this.starting = false;
      }
    });
  }

  get running(): boolean {
    return !!this.status?.running || this.status?.progress?.status === 'RUNNING';
  }

  /** Manual monitoring: read the current state of the load and the batch log (nothing refreshes on its own). */
  refresh(): void {
    this.refreshing = true;
    this.service.historicalStatus().subscribe({
      next: (status) => {
        this.status = status;
        this.refreshedAt = new Date();
        this.refreshing = false;
        if (!this.running && status.progress?.batch_id) {
          this.expanded = status.progress.batch_id;
        }
      },
      error: () => (this.refreshing = false)
    });
    this.offset = 0;
    this.loadLogs();
  }

  get done(): number {
    return this.activeFiles.filter((f) => !['PENDING', 'LOADING'].includes(f.status)).length;
  }

  /** Files of the run that were not excluded by the user. */
  get activeFiles() {
    return (this.status?.progress?.files ?? []).filter((f) => f.status !== 'EXCLUDED');
  }

  get excludedCount(): number {
    return (this.status?.progress?.files ?? []).filter((f) => f.status === 'EXCLUDED').length;
  }

  get total(): number {
    return this.activeFiles.length;
  }

  get percent(): number {
    return this.total ? Math.round((this.done / this.total) * 100) : 0;
  }

  get liveTotals(): { inserted: number; updated: number; skipped: number } {
    const files = this.status?.progress?.files ?? [];
    return {
      inserted: files.reduce((s, f) => s + (f.inserted ?? 0), 0),
      updated: files.reduce((s, f) => s + (f.updated ?? 0), 0),
      skipped: files.reduce((s, f) => s + Math.max(f.skipped ?? 0, 0), 0)
    };
  }

  // ---------------------------------------------------------------- batch log

  loadLogs(): void {
    this.logsLoading = true;
    this.service
      .historicalLogs({ status: this.statusFilter, limit: this.pageSize, offset: this.offset })
      .subscribe({
        next: (page) => {
          this.logs = page;
          this.logsLoading = false;
        },
        error: () => (this.logsLoading = false)
      });
  }

  setStatusFilter(status: BatchStatusValue | ''): void {
    this.statusFilter = status;
    this.offset = 0;
    this.loadLogs();
  }

  get allCount(): number {
    const c = this.logs?.counts;
    return c ? c.SUCCESS + c.PARTIAL + c.FAILED : 0;
  }

  page(delta: number): void {
    const next = this.offset + delta * this.pageSize;
    if (next >= 0 && next < (this.logs?.total ?? 0)) {
      this.offset = next;
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
    const s = Math.round(ms / 1000);
    return s < 60 ? `${s} s` : `${Math.floor(s / 60)} min ${s % 60} s`;
  }

  size(bytes: number): string {
    return bytes < 1024 * 1024 ? `${(bytes / 1024).toFixed(0)} KB` : `${(bytes / 1048576).toFixed(1)} MB`;
  }
}
