import { CommonModule } from '@angular/common';
import { Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';

import { SimulatorInfo, SimulatorResult } from '../../../core/models/batch.model';
import { BatchService } from '../../../core/services/batch.service';

const STEP_MS = 5 * 60_000;

/** datetime-local value ("2026-09-29T10:00") <-> a Date read as plant local clock time. */
function toInput(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function fromInput(value: string): Date | null {
  if (!value) {
    return null;
  }
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? null : d;
}

@Component({
  selector: 'app-snapshot-simulator',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  templateUrl: './snapshot-simulator.component.html',
  styleUrl: './snapshot-simulator.component.scss'
})
export class SnapshotSimulatorComponent implements OnInit {
  info: SimulatorInfo | null = null;
  infoError: string | null = null;

  start = '';
  end = '';
  seed: number | null = null;
  overwrite = false;
  sourceFrom = '';
  sourceTo = '';
  showAdvanced = false;

  running = false;
  result: SimulatorResult | null = null;
  error: string | null = null;

  constructor(private service: BatchService) {}

  ngOnInit(): void {
    this.service.simulatorInfo().subscribe({
      next: (info) => {
        this.info = info;
        // default: the hour right after the newest stored telemetry
        const latest = info.latest_telemetry ? new Date(info.latest_telemetry.slice(0, 19)) : new Date();
        const start = new Date(Math.ceil((latest.getTime() + 1) / STEP_MS) * STEP_MS);
        this.start = toInput(start);
        this.end = toInput(new Date(start.getTime() + 55 * 60_000));
      },
      error: (err) => {
        this.infoError = err?.error?.detail || 'Could not load the simulator settings. Is the backend running?';
      }
    });
  }

  /** Start rounded up and end rounded down to the 5-minute grid, as the backend does. */
  private get grid(): { start: Date; end: Date } | null {
    const s = fromInput(this.start);
    const e = fromInput(this.end);
    if (!s || !e) {
      return null;
    }
    return { start: new Date(Math.ceil(s.getTime() / STEP_MS) * STEP_MS), end: new Date(Math.floor(e.getTime() / STEP_MS) * STEP_MS) };
  }

  get fileCount(): number {
    const g = this.grid;
    return g && g.end >= g.start ? Math.round((g.end.getTime() - g.start.getTime()) / STEP_MS) + 1 : 0;
  }

  get firstName(): string {
    return this.grid ? this.fileName(this.grid.start) : '';
  }

  get lastName(): string {
    return this.grid ? this.fileName(this.grid.end) : '';
  }

  private fileName(d: Date): string {
    const pad = (n: number) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}-${pad(d.getHours())}-${pad(d.getMinutes())}-00.json`;
  }

  get problem(): string | null {
    if (!this.start || !this.end) {
      return 'Enter a start and an end time.';
    }
    const g = this.grid;
    if (!g || g.end < g.start) {
      return 'The end must be at or after the start.';
    }
    if (this.info && this.fileCount > this.info.max_files) {
      return `That is ${this.fileCount} files; the limit is ${this.info.max_files} (7 days) per run.`;
    }
    if (this.sourceFrom && this.sourceTo && this.sourceTo < this.sourceFrom) {
      return 'The sample period ends before it starts.';
    }
    return null;
  }

  /** The source days the chosen sample period leaves. */
  get sampleDays(): number {
    return (this.info?.source_days ?? []).filter(
      (d) => (!this.sourceFrom || d >= this.sourceFrom) && (!this.sourceTo || d <= this.sourceTo)
    ).length;
  }

  setDuration(minutes: number): void {
    const s = fromInput(this.start);
    if (s) {
      this.end = toInput(new Date(s.getTime() + minutes * 60_000 - STEP_MS));
    }
  }

  generate(): void {
    if (this.problem || this.running) {
      return;
    }
    this.running = true;
    this.error = null;
    this.result = null;
    this.service
      .simulate({
        start: `${this.start}:00`,
        end: `${this.end}:00`,
        seed: this.seed === null || (this.seed as unknown) === '' ? null : Number(this.seed),
        overwrite: this.overwrite,
        source_from: this.sourceFrom || null,
        source_to: this.sourceTo || null
      })
      .subscribe({
        next: (result) => {
          this.result = result;
          this.running = false;
        },
        error: (err) => {
          this.error = err?.error?.detail || 'The simulator failed. Is the backend running?';
          this.running = false;
        }
      });
  }

  get dayMap(): { day: string; source: string }[] {
    return Object.entries(this.result?.source_days ?? {}).map(([day, source]) => ({ day, source }));
  }

  plantTime(iso: string | null | undefined): string {
    return iso ? iso.slice(0, 16).replace('T', ' ') : '—';
  }
}
