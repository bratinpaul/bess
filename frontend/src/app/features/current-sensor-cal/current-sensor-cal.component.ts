import { CommonModule } from '@angular/common';
import { Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { CalSystem, CurrentSensorCal, CurrentSensorCalValues } from '../../core/models/current-sensor-cal.model';
import { CurrentSensorCalService } from '../../core/services/current-sensor-cal.service';
import { TableColumn, TableRow } from '../telemetry/table/table-column';
import { TelemetryTableComponent } from '../telemetry/table/telemetry-table.component';

const COLUMNS: TableColumn[] = [
  { key: 'system_code', label: 'System', kind: 'text', group: 'Key', locked: true },
  { key: 'calibrated_on', label: 'Calibrated On', kind: 'text', group: 'Key', locked: true },
  { key: 'offset_a', label: 'Offset (A)', kind: 'number', group: 'Calibration', locked: true },
  { key: 'gain_error_pct', label: 'Gain Error (%)', kind: 'number', group: 'Calibration', locked: true },
  { key: 'drift_a_per_day', label: 'Drift (A / day)', kind: 'number', group: 'Calibration', locked: true },
  { key: 'days_since', label: 'Days Since', kind: 'number', group: 'Projection', locked: true },
  { key: 'projected_offset_a', label: 'Projected Offset (A)', kind: 'number', group: 'Projection', locked: true },
  { key: 'status', label: 'Status', kind: 'text', group: 'Projection', locked: true }
];

interface Field {
  key: keyof CurrentSensorCalValues;
  label: string;
  step: number;
  min: number;
  max: number;
  help: string;
}

const FIELDS: Field[] = [
  { key: 'offset_a', label: 'Offset (A)', step: 0.01, min: -1000, max: 1000, help: 'reading at zero current' },
  { key: 'gain_error_pct', label: 'Gain error (%)', step: 0.01, min: -100, max: 100, help: 'scale error of the reading' },
  { key: 'drift_a_per_day', label: 'Offset drift (A / day)', step: 0.001, min: -100, max: 100, help: 'how fast the offset moves' }
];

interface EditState {
  row: CurrentSensorCal;
  values: CurrentSensorCalValues;
}

/** Core -> Reference -> Current Sensor Calibration: offset, gain error and offset drift of each fleet system's current
 *  sensor per calibration (battery_master.current_sensor_cal) - with the offset the drift projects to since - view,
 *  edit and delete. These are the errors coulomb-counted SOC accumulates between recalibrations. */
@Component({
  selector: 'app-current-sensor-cal',
  standalone: true,
  imports: [CommonModule, FormsModule, TelemetryTableComponent],
  templateUrl: './current-sensor-cal.component.html',
  styleUrls: ['../calendar/calendar.component.scss', '../aging-snapshot/aging-snapshot.component.scss']
})
export class CurrentSensorCalComponent implements OnInit {
  readonly columns = COLUMNS;
  readonly fields = FIELDS;

  systems: CalSystem[] = [];
  rows: CurrentSensorCal[] = [];
  tableRows: TableRow[] = [];
  loading = true;
  error: string | null = null;
  filterSystem: number | null = null;
  filterStart = '';
  filterEnd = '';

  edit: EditState | null = null;
  saving = false;
  editError: string | null = null;
  toDelete: CurrentSensorCal | null = null;
  deleting = false;
  deleteError: string | null = null;

  constructor(private service: CurrentSensorCalService) {}

  ngOnInit(): void {
    this.service.systems().subscribe({ next: (s) => (this.systems = s), error: () => (this.systems = []) });
    this.fetchRows();
  }

  get calibratedSystems(): CalSystem[] {
    return this.systems.filter((s) => s.calibrations > 0);
  }

  get stats() {
    const current = this.rows.filter((r) => !r.superseded_on);
    const proj = current.map((r) => Math.abs(r.projected_offset_a ?? 0));
    const dates = this.rows.map((r) => r.calibrated_on).sort();
    return {
      systems: new Set(this.rows.map((r) => r.system_id)).size,
      calibrations: this.rows.length,
      latest: dates[dates.length - 1] ?? null,
      worst: proj.length ? Math.max(...proj) : null,
      oldest: current.length ? Math.max(...current.map((r) => r.days_since ?? 0)) : null
    };
  }

  fetchRows(): void {
    this.loading = true;
    this.error = null;
    this.service.list(this.filterSystem, this.filterStart || undefined, this.filterEnd || undefined).subscribe({
      next: (rows) => {
        this.rows = rows;
        this.tableRows = rows.map(
          (r) => ({ ...r, status: r.superseded_on ? `superseded ${r.superseded_on}` : 'current' }) as unknown as TableRow
        );
        this.loading = false;
      },
      error: () => {
        this.error = 'Could not load the sensor calibrations. Is the backend running?';
        this.loading = false;
      }
    });
  }

  clearFilters(): void {
    this.filterSystem = null;
    this.filterStart = this.filterEnd = '';
    this.fetchRows();
  }

  num(v: number | null | undefined, d = 2): string {
    return typeof v === 'number' && Number.isFinite(v) ? v.toFixed(d) : '—';
  }

  // ---------------------------------------------------------------- edit / delete

  private find(row: TableRow): CurrentSensorCal | undefined {
    const r = row as unknown as CurrentSensorCal;
    return this.rows.find((x) => x.system_id === r.system_id && x.calibrated_on === r.calibrated_on);
  }

  openEdit(row: TableRow): void {
    const r = this.find(row);
    if (!r) {
      return;
    }
    this.editError = null;
    this.edit = { row: r, values: { offset_a: r.offset_a, gain_error_pct: r.gain_error_pct, drift_a_per_day: r.drift_a_per_day } };
  }

  get editProblem(): string | null {
    const v = this.edit?.values;
    if (!v) {
      return null;
    }
    for (const f of FIELDS) {
      const x = v[f.key] as unknown;
      if (x === null || x === undefined || x === '') {
        continue;
      }
      const n = Number(x);
      if (!Number.isFinite(n) || n < f.min || n > f.max) {
        return `${f.label} must be between ${f.min} and ${f.max}`;
      }
    }
    return null;
  }

  /** What the edited drift does to the offset by now (same day count as the stored row). */
  get editProjection(): number | null {
    const e = this.edit;
    if (!e || this.editProblem) {
      return null;
    }
    const o = e.values.offset_a as unknown;
    const d = e.values.drift_a_per_day as unknown;
    if (o === null || o === '' || d === null || d === '') {
      return null;
    }
    return Number(o) + Number(d) * (e.row.days_since ?? 0);
  }

  save(): void {
    const e = this.edit;
    if (!e || this.editProblem) {
      return;
    }
    const n = (x: unknown) => (x === null || x === undefined || x === '' ? null : Number(x));
    this.saving = true;
    this.editError = null;
    this.service
      .update(e.row, { offset_a: n(e.values.offset_a), gain_error_pct: n(e.values.gain_error_pct), drift_a_per_day: n(e.values.drift_a_per_day) })
      .subscribe({
        next: () => {
          this.saving = false;
          this.edit = null;
          this.fetchRows();
        },
        error: (err) => {
          this.saving = false;
          const d = err?.error?.detail;
          this.editError = Array.isArray(d) ? d.map((x: { loc: string[]; msg: string }) => `${x.loc?.[x.loc.length - 1]}: ${x.msg}`).join('; ') : d || 'Saving failed.';
        }
      });
  }

  confirmDelete(row: TableRow): void {
    this.deleteError = null;
    this.toDelete = this.find(row) ?? null;
  }

  deleteConfirmed(): void {
    const t = this.toDelete;
    if (!t) {
      return;
    }
    this.deleting = true;
    this.service.delete(t).subscribe({
      next: () => {
        this.deleting = false;
        this.toDelete = null;
        this.fetchRows();
        this.service.systems().subscribe((s) => (this.systems = s));
      },
      error: (err) => {
        this.deleting = false;
        this.deleteError = err?.error?.detail || 'Deleting failed.';
      }
    });
  }
}
