import { CommonModule } from '@angular/common';
import { Component, OnInit, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';

import { HeatHorizonScore, HeatOptions, HeatRun, HeatRunRequest, HeatSystemSummary } from '../../../core/models/heat-load.model';
import { HeatLoadService } from '../../../core/services/heat-load.service';

/** ML Model -> Heat Load Model: compute a heat-load run (heat-balance ledger calibrated to a measured reference,
 *  operational forecast backtest by issue vintage, thermal-design sizing) and review the calibration and the scores. */
@Component({
  selector: 'app-heat-load-model',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  templateUrl: './heat-load-model.component.html',
  styleUrl: './heat-load-model.component.scss'
})
export class HeatLoadModelComponent implements OnInit {
  private service = inject(HeatLoadService);

  options: HeatOptions | null = null;
  optionsError: string | null = null;
  form: HeatRunRequest | null = null;
  selectedSystems = new Set<number>();
  ui = { horizons: '15, 30, 60, 120, 240', designAmbient: '', eol: '', unitCap: '', trainPct: 75 };

  running = false;
  runError: string | null = null;
  runs: HeatRun[] = [];
  selected: HeatRun | null = null;
  systemKey = '';
  toDelete: HeatRun | null = null;
  showWarnings = false;
  readonly Math = Math;

  ngOnInit(): void {
    this.service.options().subscribe({
      next: (o) => {
        this.options = o;
        this.form = { ...o.defaults };
        this.selectedSystems = new Set(o.defaults.system_ids);
        this.ui.horizons = o.defaults.horizons.join(', ');
        this.ui.trainPct = Math.round(o.defaults.train_frac * 100);
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
    return s.length ? { first: s.map((x) => x.first_day).sort()[0], last: s.map((x) => x.last_day).sort().slice(-1)[0] } : null;
  }

  private optional(v: string): number | null {
    const t = String(v ?? '').trim();
    return t === '' ? null : Number(t);
  }

  run(): void {
    if (!this.form || !this.selectedSystems.size) {
      return;
    }
    const horizons = this.ui.horizons.split(/[,\s]+/).map(Number).filter((x) => Number.isFinite(x) && x > 0);
    const body: HeatRunRequest = {
      ...this.form,
      system_ids: [...this.selectedSystems],
      run_name: this.form.run_name?.trim() || null,
      horizons,
      train_frac: this.ui.trainPct / 100,
      design_ambient_c: this.optional(this.ui.designAmbient),
      eol_resistance_pct: this.optional(this.ui.eol),
      unit_capacity_kw: this.optional(this.ui.unitCap)
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

  private show(r: HeatRun): void {
    this.selected = r;
    this.systemKey = r.system_ids.length ? String(r.system_ids[0]) : '';
  }

  confirmDelete(r: HeatRun): void {
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

  get summary(): HeatSystemSummary | null {
    return this.selected?.summary?.systems?.[this.systemKey] ?? null;
  }

  get horizonRows(): { h: string; s: HeatHorizonScore }[] {
    return Object.entries(this.summary?.forecast?.by_horizon ?? {}).map(([h, s]) => ({ h, s }));
  }

  get rBands(): { dir: string; bands: { band: string; r: number; observed: boolean }[] }[] {
    const bh = this.selected?.models?.[this.systemKey]?.battery_heat ?? {};
    return Object.entries(bh).map(([dir, m]) => ({
      dir,
      bands: Object.entries(m.r_ohm_by_soc_band).map(([b, r]) => ({ band: `${Number(b) * 10}–${Number(b) * 10 + 10}`, r, observed: m.observed_bands.includes(Number(b)) }))
    }));
  }

  get pcsModel() {
    return this.selected?.models?.[this.systemKey]?.pcs_loss ?? null;
  }

  get topFeatures(): { f: string; v: number }[] {
    return Object.entries(this.summary?.forecast?.importance ?? {}).sort((a, b) => b[1] - a[1]).slice(0, 8).map(([f, v]) => ({ f, v }));
  }

  systemName(id: number | string): string {
    return this.options?.systems.find((s) => s.system_id === Number(id))?.system_name ?? `#${id}`;
  }

  pct(v: number | null | undefined, d = 1): string {
    return v === null || v === undefined || !Number.isFinite(v) ? '—' : (v * 100).toFixed(d);
  }

  num(v: number | null | undefined, d = 2): string {
    if (v === null || v === undefined || !Number.isFinite(v)) {
      return '—';
    }
    const x = Math.abs(v) < 0.5 * 10 ** -d ? 0 : v;
    return x.toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });
  }
}
