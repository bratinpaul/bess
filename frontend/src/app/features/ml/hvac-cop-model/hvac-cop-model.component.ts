import { CommonModule } from '@angular/common';
import { Component, OnInit, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';

import { CopOptions, CopRun, CopRunRequest, CopUnitSummary } from '../../../core/models/hvac-cop.model';
import { HvacCopService } from '../../../core/services/hvac-cop.service';

/** ML Model -> HVAC COP Model: fit the COP / capacity performance maps, the Carnot-anchored grey-box and the GBM residual per
 *  HVAC unit on steady-state intervals, and review the scores, closure audit and scorecard. */
@Component({
  selector: 'app-hvac-cop-model',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  templateUrl: './hvac-cop-model.component.html',
  styleUrl: './hvac-cop-model.component.scss'
})
export class HvacCopModelComponent implements OnInit {
  private service = inject(HvacCopService);

  options: CopOptions | null = null;
  optionsError: string | null = null;
  form: CopRunRequest | null = null;
  selectedUnits = new Set<number>();
  ui = { trainPct: 70, rated: '' };

  running = false;
  runError: string | null = null;
  runs: CopRun[] = [];
  selected: CopRun | null = null;
  unitKey = '';
  toDelete: CopRun | null = null;
  showWarnings = false;
  readonly Math = Math;

  ngOnInit(): void {
    this.service.options().subscribe({
      next: (o) => {
        this.options = o;
        this.form = { ...o.defaults };
        this.selectedUnits = new Set(o.defaults.hvac_ids);
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

  toggleUnit(id: number): void {
    if (this.selectedUnits.has(id)) {
      this.selectedUnits.delete(id);
    } else {
      this.selectedUnits.add(id);
    }
  }

  get span(): { first: string; last: string } | null {
    const s = this.options?.units.filter((x) => this.selectedUnits.has(x.hvac_id)) ?? [];
    return s.length ? { first: s.map((x) => x.first_day).sort()[0], last: s.map((x) => x.last_day).sort().slice(-1)[0] } : null;
  }

  run(): void {
    if (!this.form || !this.selectedUnits.size) {
      return;
    }
    const rated = String(this.ui.rated ?? '').trim();
    const body: CopRunRequest = {
      ...this.form, hvac_ids: [...this.selectedUnits], run_name: this.form.run_name?.trim() || null,
      train_frac: this.ui.trainPct / 100, rated_capacity_kw: rated === '' ? null : Number(rated)
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

  private show(r: CopRun): void {
    this.selected = r;
    this.unitKey = r.hvac_ids.length ? String(r.hvac_ids[0]) : '';
  }

  confirmDelete(r: CopRun): void {
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

  get summary(): CopUnitSummary | null {
    return this.selected?.summary?.units?.[this.unitKey] ?? null;
  }

  get model() {
    return this.selected?.models?.[this.unitKey] ?? null;
  }

  get scoreRows(): { key: string; label: string; train: Record<string, number | null | undefined> | null; test: Record<string, number | null | undefined> }[] {
    const s = this.summary?.scores;
    if (!s) {
      return [];
    }
    const label: Record<string, string> = {
      map: 'COP · performance map', grey: 'COP · Carnot grey-box', hybrid: 'COP · map + GBM residual', constant: 'COP · constant (baseline)',
      capacity_map: 'Capacity map (kW)', power: 'Power = CAP / COP (kW)'
    };
    return Object.entries(s).map(([key, v]) => ({ key, label: label[key] ?? key, train: (v.train as never) ?? null, test: v.test as never }));
  }

  get importance(): { f: string; v: number }[] {
    return Object.entries(this.model?.gbm_importance ?? {}).sort((a, b) => b[1] - a[1]).slice(0, 8).map(([f, v]) => ({ f, v }));
  }

  unitName(id: number | string): string {
    const u = this.options?.units.find((x) => x.hvac_id === Number(id));
    return u ? `${u.hvac_code} · ${u.site_name ?? ''}` : `#${id}`;
  }

  closure(key: string): number | null {
    const v = this.summary?.closure?.[key];
    return typeof v === 'number' ? v : null;
  }

  coef(v: number[] | undefined, d = 4): string {
    return (v ?? []).map((x) => this.num(x, d)).join(', ');
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
