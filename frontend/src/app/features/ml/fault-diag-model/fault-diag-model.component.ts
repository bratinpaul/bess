import { CommonModule } from '@angular/common';
import { Component, OnInit, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';

import { AuthService } from '../../../core/auth/auth.service';
import { HasPermissionDirective } from '../../../core/auth/has-permission.directive';

import { FdCard, FdOptions, FdRun, FdScanResult, FdTrainRequest } from '../../../core/models/fault-diag.model';
import { FaultDiagService } from '../../../core/services/fault-diag.service';

/** ML Model -> Fault Classifier: train the signature engine + LightGBM / XGBoost fusion on the confirmed fault episodes,
 *  review the out-of-fold and forward scorecards, publish to fault_prediction and scan telemetry for candidates. */
@Component({
  selector: 'app-fault-diag-model',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink, HasPermissionDirective],
  templateUrl: './fault-diag-model.component.html',
  styleUrl: './fault-diag-model.component.scss'
})
export class FaultDiagModelComponent implements OnInit {
  private service = inject(FaultDiagService);
  readonly auth = inject(AuthService);

  options: FdOptions | null = null;
  optionsError: string | null = null;
  form: FdTrainRequest | null = null;
  families = new Set<string>();

  running = false;
  runError: string | null = null;
  runs: FdRun[] = [];
  selected: FdRun | null = null;
  toDelete: FdRun | null = null;
  showWarnings = true;
  showAdvanced = false;
  showClasses = false;

  scanForm = { system_id: 0, date_from: '', date_to: '', step_min: 15, threshold: 0.5 };
  scanning = false;
  scanResult: FdScanResult | null = null;
  scanError: string | null = null;
  publishMsg: string | null = null;

  readonly Math = Math;

  ngOnInit(): void {
    this.service.options().subscribe({
      next: (o) => {
        this.options = o;
        this.form = { ...o.defaults, date_from: o.episodes.date_from, date_to: o.episodes.date_to };
        this.families = new Set(o.defaults.families);
        const sys = o.systems.find((s) => o.episodes.telemetry_systems.includes(s.system_id)) ?? o.systems[0];
        if (sys) {
          this.scanForm = { ...this.scanForm, system_id: sys.system_id, date_from: sys.date_from, date_to: sys.date_to };
        }
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

  toggleFamily(k: string): void {
    if (this.families.has(k)) {
      this.families.delete(k);
    } else {
      this.families.add(k);
    }
  }

  run(): void {
    if (!this.form || !this.families.size) {
      return;
    }
    const body: FdTrainRequest = { ...this.form, families: [...this.families], run_name: this.form.run_name?.trim() || null };
    this.running = true;
    this.runError = null;
    this.service.createRun(body).subscribe({
      next: (r) => {
        this.running = false;
        this.selected = r;
        this.scanResult = null;
        this.publishMsg = null;
        this.loadRuns();
      },
      error: (err) => {
        this.running = false;
        this.runError = this.errorText(err, 'The run failed.');
        this.loadRuns();
      }
    });
  }

  open(id: number): void {
    this.service.run(id).subscribe({
      next: (r) => {
        this.selected = r;
        this.scanResult = null;
        this.publishMsg = null;
      }
    });
  }

  makeDefault(r: FdRun): void {
    this.service.makeDefault(r.run_id).subscribe({ next: () => this.loadRuns() });
  }

  publish(): void {
    if (!this.selected) {
      return;
    }
    this.publishMsg = 'Publishing…';
    this.service.publish(this.selected.run_id).subscribe({
      next: (r) => {
        this.publishMsg = `${r.rows} out-of-fold predictions written to fault_prediction as ${r.model_version}.`;
        this.open(this.selected!.run_id);
      },
      error: (err) => (this.publishMsg = this.errorText(err, 'Publishing failed.'))
    });
  }

  scan(): void {
    if (!this.selected) {
      return;
    }
    this.scanning = true;
    this.scanError = null;
    this.scanResult = null;
    this.service.scan(this.selected.run_id, { ...this.scanForm, threshold: Number(this.scanForm.threshold) }).subscribe({
      next: (r) => {
        this.scanning = false;
        this.scanResult = r;
      },
      error: (err) => {
        this.scanning = false;
        this.scanError = this.errorText(err, 'The scan failed.');
      }
    });
  }

  confirmDelete(r: FdRun): void {
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

  get scanSystem() {
    return this.options?.systems.find((s) => s.system_id === Number(this.scanForm.system_id)) ?? null;
  }

  onScanSystem(): void {
    const s = this.scanSystem;
    if (s) {
      this.scanForm.date_from = s.date_from;
      this.scanForm.date_to = s.date_to;
    }
  }

  get cardRows(): { key: 'engine' | 'ml' | 'fused'; label: string; oof: FdCard; fwd: FdCard | null }[] {
    const m = this.selected?.metrics;
    if (!m) {
      return [];
    }
    const label = { engine: 'Signature / Bayesian engine (no training)', ml: `${this.algoName} classifier`, fused: 'Fused (geometric mean, calibrated)' };
    return (['engine', 'ml', 'fused'] as const).map((k) => ({ key: k, label: label[k], oof: m.oof[k], fwd: m.forward?.[k] ?? null }));
  }

  get algoName(): string {
    const p = this.selected?.params;
    return p ? `${p.algorithm === 'xgboost' ? 'XGBoost' : 'LightGBM'} ${p.structure === 'hierarchical' ? '(subsystem → fault)' : '(flat)'}` : 'ML';
  }

  get fused(): FdCard | null {
    return this.selected?.metrics?.oof.fused ?? null;
  }

  get familyImportance(): { k: string; v: number }[] {
    const f = this.selected?.summary?.family_importance ?? {};
    const total = Object.values(f).reduce((a, b) => a + b, 0) || 1;
    return Object.entries(f).map(([k, v]) => ({ k, v: v / total })).sort((a, b) => b.v - a.v);
  }

  familyLabel(k: string): string {
    return this.options?.families.find((f) => f.key === k)?.label ?? k;
  }

  className(code: string): string {
    return this.options?.classes.find((c) => c.fault_code === code)?.fault_name ?? '';
  }

  get unavailable(): string[] {
    const c = this.selected?.summary?.signature_coverage ?? {};
    return Object.entries(c).filter(([, v]) => v === 'unavailable').map(([k]) => k);
  }

  get muted() {
    return (this.selected?.summary?.signature_health ?? []).filter((s) => s.muted);
  }

  systemNames(ids: number[]): string {
    return ids.map((id) => this.systemName(id)).join(', ');
  }

  systemName(id: number): string {
    return this.options?.systems.find((s) => s.system_id === id)?.system_name ?? `#${id}`;
  }

  private errorText(err: { error?: { detail?: unknown } }, fallback: string): string {
    const d = err?.error?.detail as { message?: string } | string | { msg: string }[] | undefined;
    if (typeof d === 'string') {
      return d;
    }
    if (Array.isArray(d)) {
      return d.map((x) => x.msg).join('; ');
    }
    return d?.message || fallback;
  }

  pct(v: number | null | undefined, d = 1): string {
    return v === null || v === undefined || !Number.isFinite(v) ? '—' : (v * 100).toFixed(d);
  }

  num(v: number | null | undefined, d = 2): string {
    if (v === null || v === undefined || !Number.isFinite(v)) {
      return '—';
    }
    return v.toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });
  }
}
