import { CommonModule } from '@angular/common';
import { Component, OnDestroy, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';

import {
  WeakOptions,
  WeakParamSpec,
  WeakPreview,
  WeakRun,
  WeakSystemCoverage
} from '../../../core/models/weak-module.model';
import { WeakModuleService } from '../../../core/services/weak-module.service';

/** ML Model -> Weak Module Model: configure and run Isolation Forest + DBSCAN weak module detection. */
@Component({
  selector: 'app-weak-module-model',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  templateUrl: './weak-module-model.component.html',
  styleUrls: ['../model-training/model-training.component.scss', './weak-module-model.component.scss']
})
export class WeakModuleModelComponent implements OnInit, OnDestroy {
  options: WeakOptions | null = null;
  optionsError: string | null = null;

  systemId: number | null = null;
  dateFrom = '';
  dateTo = '';
  grain: 'day' | 'hour' = 'day';
  groups = new Set<string>();
  ifParams: Record<string, number | string> = {};
  dbParams: Record<string, number | string> = {};
  minShare = 0.4;
  runName = '';

  preview: WeakPreview | null = null;
  previewing = false;
  running = false;
  runError: string | null = null;

  runs: WeakRun[] = [];
  runsLoading = true;

  private previewTimer?: ReturnType<typeof setTimeout>;

  constructor(private service: WeakModuleService, private router: Router) {}

  ngOnInit(): void {
    this.service.options().subscribe({
      next: (options) => {
        this.options = options;
        this.groups = new Set(options.feature_groups.map((g) => g.key));
        this.minShare = options.default_min_anomalous_share;
        this.resetParams();
        const first = options.systems[0];
        if (first) {
          this.selectSystem(first.battery_system_id);
        }
      },
      error: (err) =>
        (this.optionsError = err?.status === 0
          ? 'Could not reach the ML service. Is it running on port 8100?'
          : 'Could not load the options.')
    });
    this.loadRuns();
  }

  ngOnDestroy(): void {
    clearTimeout(this.previewTimer);
  }

  // ---------------------------------------------------------------- inputs

  get system(): WeakSystemCoverage | undefined {
    return this.options?.systems.find((s) => s.battery_system_id === this.systemId);
  }

  selectSystem(id: number): void {
    this.systemId = id;
    const s = this.system;
    this.dateFrom = s?.date_from ?? '';
    this.dateTo = s?.date_to ?? '';
    this.schedulePreview();
  }

  specs(key: 'isolation_forest' | 'dbscan'): WeakParamSpec[] {
    return this.options?.models.find((m) => m.key === key)?.params ?? [];
  }

  resetParams(): void {
    this.ifParams = Object.fromEntries(this.specs('isolation_forest').map((p) => [p.name, p.default]));
    this.dbParams = Object.fromEntries(this.specs('dbscan').map((p) => [p.name, p.default]));
  }

  toggleGroup(key: string): void {
    this.groups.has(key) ? this.groups.delete(key) : this.groups.add(key);
    this.groups = new Set(this.groups);
  }

  get featureCount(): number {
    return (this.options?.feature_groups ?? []).filter((g) => this.groups.has(g.key)).reduce((n, g) => n + g.features.length, 0);
  }

  schedulePreview(): void {
    clearTimeout(this.previewTimer);
    this.previewTimer = setTimeout(() => this.loadPreview(), 400);
  }

  private loadPreview(): void {
    if (!this.systemId) {
      return;
    }
    this.previewing = true;
    this.service
      .preview({ battery_system_id: this.systemId, date_from: this.dateFrom || null, date_to: this.dateTo || null, grain: this.grain })
      .subscribe({
        next: (p) => {
          this.preview = p;
          this.previewing = false;
        },
        error: () => {
          this.preview = null;
          this.previewing = false;
        }
      });
  }

  get autoMinSamples(): number | null {
    return this.preview?.rows_per_module ? Math.max(5, 2 * this.preview.rows_per_module) : null;
  }

  get canRun(): boolean {
    return !!this.systemId && this.groups.size > 0 && !this.running && (this.preview?.rows ?? 0) >= 20;
  }

  // ---------------------------------------------------------------- run

  run(): void {
    if (!this.canRun || !this.systemId) {
      return;
    }
    this.running = true;
    this.runError = null;
    this.service
      .detect({
        battery_system_id: this.systemId,
        date_from: this.dateFrom || null,
        date_to: this.dateTo || null,
        grain: this.grain,
        feature_groups: Array.from(this.groups),
        if_params: this.ifParams,
        db_params: this.dbParams,
        min_anomalous_share: Number(this.minShare),
        run_name: this.runName.trim() || null
      })
      .subscribe({
        next: (run) => {
          this.running = false;
          this.router.navigate(['/ml/weak-modules'], { queryParams: { run: run.run_id } });
        },
        error: (err) => {
          const d = err?.error?.detail;
          this.runError = typeof d === 'string' ? d : d?.message || 'Detection failed.';
          this.running = false;
          this.loadRuns();
        }
      });
  }

  // ---------------------------------------------------------------- history

  loadRuns(): void {
    this.runsLoading = true;
    this.service.runs().subscribe({
      next: (runs) => {
        this.runs = runs;
        this.runsLoading = false;
      },
      error: () => (this.runsLoading = false)
    });
  }

  deleteRun(run: WeakRun, event: Event): void {
    event.stopPropagation();
    if (!window.confirm(`Delete run #${run.run_id} and its results?`)) {
      return;
    }
    this.service.deleteRun(run.run_id).subscribe(() => this.loadRuns());
  }

  open(run: WeakRun): void {
    if (run.status === 'COMPLETED') {
      this.router.navigate(['/ml/weak-modules'], { queryParams: { run: run.run_id } });
    }
  }

  window(run: WeakRun): string {
    return `${run.date_from ?? 'start'} → ${run.date_to ?? 'end'}`;
  }

  duration(ms: number | null): string {
    return ms === null ? '' : ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
  }
}
