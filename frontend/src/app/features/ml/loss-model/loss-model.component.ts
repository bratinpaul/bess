import { CommonModule } from '@angular/common';
import { Component, OnInit, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';

import { LossModels, LossOptions, LossRun, LossRunRequest, LossSystemSummary } from '../../../core/models/loss-decomposition.model';
import { LossDecompositionService } from '../../../core/services/loss-decomposition.service';

const COUNTER_LABELS: Record<string, string> = {
  bms_charge: 'BMS cumulative charge',
  bms_discharge: 'BMS cumulative discharge',
  pcs_import: 'PCS AC import',
  pcs_export: 'PCS AC export',
  poi_import: 'POI import',
  poi_export: 'POI export'
};

/** ML Model -> Loss Model: compute a loss-decomposition / benchmarking run (per-interval ledger, expected-loss models on a
 *  baseline window, daily scorecard) for one or more battery systems, and review the fitted models and the closure audit. */
@Component({
  selector: 'app-loss-model',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  templateUrl: './loss-model.component.html',
  styleUrl: './loss-model.component.scss'
})
export class LossModelComponent implements OnInit {
  private service = inject(LossDecompositionService);

  options: LossOptions | null = null;
  optionsError: string | null = null;
  form: LossRunRequest | null = null;
  selectedSystems = new Set<number>();
  // fields shown in % / free text (blank = from the master data)
  ui = { idlePct: 1, refLoadPct: 50, minCyclePct: 5, xfmrKva: '', selfDischarge: '', guarantee: '' };

  running = false;
  runError: string | null = null;
  runs: LossRun[] = [];
  selected: LossRun | null = null;
  systemKey = '';
  toDelete: LossRun | null = null;
  showWarnings = false;

  readonly counterLabels = COUNTER_LABELS;
  readonly Math = Math;

  ngOnInit(): void {
    this.service.options().subscribe({
      next: (o) => {
        this.options = o;
        this.form = { ...o.defaults };
        this.selectedSystems = new Set(o.defaults.system_ids);
      },
      error: () => (this.optionsError = 'Could not reach the ML service (port 8100).')
    });
    this.loadRuns(true);
  }

  loadRuns(selectLatest = false): void {
    this.service.runs().subscribe({
      next: (r) => {
        this.runs = r;
        const latest = r.find((x) => x.status === 'COMPLETED');
        if (selectLatest && latest && !this.selected) {
          this.open(latest.run_id);
        }
      },
      error: () => (this.runs = [])
    });
  }

  toggleSystem(id: number): void {
    if (this.selectedSystems.has(id)) {
      this.selectedSystems.delete(id);
    } else {
      this.selectedSystems.add(id);
    }
  }

  get span(): { first: string; last: string } | null {
    const s = this.options?.systems.filter((x) => this.selectedSystems.has(x.system_id)) ?? [];
    if (!s.length) {
      return null;
    }
    return { first: s.map((x) => x.first_day).sort()[0], last: s.map((x) => x.last_day).sort().slice(-1)[0] };
  }

  private optional(v: string): number | null {
    const t = String(v ?? '').trim();
    return t === '' ? null : Number(t);
  }

  run(): void {
    if (!this.form || !this.selectedSystems.size) {
      return;
    }
    const body: LossRunRequest = {
      ...this.form,
      system_ids: [...this.selectedSystems],
      run_name: this.form.run_name?.trim() || null,
      idle_frac: this.ui.idlePct / 100,
      ref_load_frac: this.ui.refLoadPct / 100,
      min_cycle_frac: this.ui.minCyclePct / 100,
      xfmr_kva: this.optional(this.ui.xfmrKva),
      self_discharge_pct_day: this.optional(this.ui.selfDischarge),
      guarantee_rte_pct: this.optional(this.ui.guarantee)
    };
    this.running = true;
    this.runError = null;
    this.service.createRun(body).subscribe({
      next: (r) => {
        this.running = false;
        this.show(r);
        this.loadRuns();
      },
      error: (err) => {
        this.running = false;
        const d = err?.error?.detail;
        this.runError = typeof d === 'string' ? d : d?.message || (Array.isArray(d) ? d.map((x: { msg: string }) => x.msg).join('; ') : 'The run failed.');
        this.loadRuns();
      }
    });
  }

  open(id: number): void {
    this.service.run(id).subscribe({ next: (r) => this.show(r) });
  }

  private show(r: LossRun): void {
    this.selected = r;
    this.systemKey = r.system_ids.length ? String(r.system_ids[0]) : '';
  }

  confirmDelete(r: LossRun): void {
    this.toDelete = r;
  }

  deleteConfirmed(): void {
    const r = this.toDelete;
    if (!r) {
      return;
    }
    this.service.deleteRun(r.run_id).subscribe({
      next: () => {
        this.toDelete = null;
        if (this.selected?.run_id === r.run_id) {
          this.selected = null;
        }
        this.loadRuns();
      }
    });
  }

  get summary(): LossSystemSummary | null {
    return this.selected?.summary?.systems?.[this.systemKey] ?? null;
  }

  get models(): LossModels | null {
    return this.selected?.models?.[this.systemKey] ?? null;
  }

  systemName(id: number | string): string {
    return this.options?.systems.find((s) => s.system_id === Number(id))?.system_name ?? `#${id}`;
  }

  fleetAvg(r: LossRun, key: 'rte_plant' | 'performance_ratio'): number | null {
    const v = (r.fleet ?? []).map((f) => f[key]).filter((x): x is number => typeof x === 'number');
    return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null;
  }

  alarmCount(r: { alarms: Record<string, number | undefined> }): number {
    return Object.values(r.alarms ?? {}).reduce((a: number, b) => a + (b ?? 0), 0);
  }

  audit(key: string): number | null {
    const v = this.summary?.audit?.[key];
    return typeof v === 'number' ? v : null;
  }

  get counterRows(): { key: string; label: string; counter: number; integral: number; diffPct: number | null; missing: number }[] {
    const c = this.summary?.audit?.counters ?? {};
    return Object.entries(c).map(([key, v]) => ({ key, label: COUNTER_LABELS[key] ?? key, counter: v.counter_kwh, integral: v.integral_kwh,
      diffPct: v.diff_pct, missing: v.days_missing }));
  }

  dirs<T>(rec: Record<string, T> | undefined): { key: string; v: T }[] {
    return Object.entries(rec ?? {}).map(([key, v]) => ({ key, v }));
  }

  pct(v: number | null | undefined, d = 2): string {
    return v === null || v === undefined || !Number.isFinite(v) ? '—' : (v * 100).toFixed(d);
  }

  num(v: number | null | undefined, d = 2): string {
    if (v === null || v === undefined || !Number.isFinite(v)) {
      return '—';
    }
    const x = Math.abs(v) < 0.5 * 10 ** -d ? 0 : v; // no "-0"
    return x.toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });
  }
}
