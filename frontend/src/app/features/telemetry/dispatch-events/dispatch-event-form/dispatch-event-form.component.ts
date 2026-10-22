import { CommonModule } from '@angular/common';
import { Component, OnInit, inject } from '@angular/core';
import { AbstractControl, FormBuilder, ReactiveFormsModule, ValidationErrors, Validators } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';

import {
  DispatchEventInput,
  DispatchEventLookups,
  DispatchStatus,
  MODE_DEFAULTS,
  modeLabel
} from '../../../../core/models/dispatch-event.model';
import { DispatchEventService } from '../../../../core/services/dispatch-event.service';

const text = (v: string | null | undefined) => (v && v.trim() ? v.trim() : null);
/** API time -> datetime-local value, keeping plant time ("2026-08-01T15:50:00+05:30" -> "2026-08-01T15:50"). */
const toInput = (iso: string | null) => (iso ? iso.slice(0, 16) : '');
/** datetime-local value -> API time; no zone, so the server reads it as plant time. */
const toApi = (value: string | null | undefined) => (value ? `${value}:00` : null);
const toNum = (v: string | null) => (v === null ? null : Number(v));

function consistencyValidator(group: AbstractControl): ValidationErrors | null {
  const v = group.value;
  const errors: ValidationErrors = {};
  if (v.effective_from && v.effective_to && v.effective_to < v.effective_from) {
    errors['endBeforeStart'] = true;
  }
  if (v.effective_from && v.issued_at && v.issued_at > v.effective_from) {
    errors['issuedAfterStart'] = true;
  }
  if (v.status === 'Active' && v.effective_to) {
    errors['activeWithEnd'] = true;
  }
  if (v.status && v.status !== 'Active' && !v.effective_to) {
    errors['endedWithoutEnd'] = true;
  }
  return Object.keys(errors).length ? errors : null;
}

const percent = [Validators.min(0), Validators.max(100)];

@Component({
  selector: 'app-dispatch-event-form',
  standalone: true,
  imports: [CommonModule, ReactiveFormsModule, RouterLink],
  templateUrl: './dispatch-event-form.component.html',
  styleUrl: './dispatch-event-form.component.scss'
})
export class DispatchEventFormComponent implements OnInit {
  private fb = inject(FormBuilder);

  dispatchId: string | null = null;
  isEditMode = false;
  loading = true;
  saving = false;
  error: string | null = null;

  lookups: DispatchEventLookups | null = null;
  modeLabel = modeLabel;

  form = this.fb.group(
    {
      dispatch_id: ['', [Validators.required, Validators.maxLength(50), Validators.pattern(/\S/)]],
      ems_id: [null as number | null, [Validators.required]],
      dispatch_mode: [null as string | null, [Validators.required]],
      command_code: [null as string | null, [Validators.required]],
      grid_service: ['NONE', [Validators.required]],
      source: ['', [Validators.maxLength(100)]],
      issued_at: [''],
      effective_from: ['', [Validators.required]],
      effective_to: [''],
      status: ['Active' as DispatchStatus, [Validators.required]],
      p_setpoint_kw: [0 as number | null, [Validators.required]],
      ramp_rate_kw_s: [null as number | null, [Validators.min(0)]],
      target_soc_pct: [null as number | null, percent],
      soc_start_pct: [null as number | null, percent],
      soc_end_pct: [null as number | null, percent],
      import_kwh: [0 as number | null, [Validators.required, Validators.min(0)]],
      export_kwh: [0 as number | null, [Validators.required, Validators.min(0)]],
      avg_price_mwh: [null as number | null],
      revenue_usd: [null as number | null],
      accepted: [true],
      note: ['', [Validators.maxLength(1000)]]
    },
    { validators: [consistencyValidator] }
  );

  constructor(
    private route: ActivatedRoute,
    private router: Router,
    private service: DispatchEventService
  ) {}

  ngOnInit(): void {
    this.dispatchId = this.route.snapshot.paramMap.get('dispatchId');
    this.isEditMode = !!this.dispatchId;
    let pending = 2;
    const done = () => (this.loading = --pending > 0);

    this.service.lookups().subscribe({
      next: (lookups) => {
        this.lookups = lookups;
        // a single EMS is the obvious choice for a new dispatch
        if (!this.isEditMode && lookups.ems.length === 1 && this.form.value.ems_id === null) {
          this.form.patchValue({ ems_id: lookups.ems[0].ems_id });
        }
        done();
      },
      error: () => {
        this.error = 'Could not load the EMS controllers and dispatch modes.';
        done();
      }
    });

    if (this.isEditMode && this.dispatchId) {
      this.form.controls.dispatch_id.disable();
      this.service.get(this.dispatchId).subscribe({
        next: (d) => {
          this.form.patchValue({
            dispatch_id: d.dispatch_id,
            ems_id: d.ems_id,
            dispatch_mode: d.dispatch_mode,
            command_code: d.command_code,
            grid_service: d.grid_service,
            source: d.source ?? '',
            issued_at: toInput(d.issued_at),
            effective_from: toInput(d.effective_from),
            effective_to: toInput(d.effective_to),
            status: d.status,
            p_setpoint_kw: toNum(d.p_setpoint_kw),
            ramp_rate_kw_s: toNum(d.ramp_rate_kw_s),
            target_soc_pct: toNum(d.target_soc_pct),
            soc_start_pct: toNum(d.soc_start_pct),
            soc_end_pct: toNum(d.soc_end_pct),
            import_kwh: toNum(d.import_kwh),
            export_kwh: toNum(d.export_kwh),
            avg_price_mwh: toNum(d.avg_price_mwh),
            revenue_usd: toNum(d.revenue_usd),
            accepted: d.accepted,
            note: d.note ?? ''
          });
          done();
        },
        error: () => {
          this.error = `Could not load dispatch ${this.dispatchId}.`;
          done();
        }
      });
    } else {
      this.service.nextId().subscribe({
        next: (id) => {
          this.form.patchValue({ dispatch_id: id });
          done();
        },
        error: () => done()
      });
    }
  }

  // ---------------------------------------------------------------- helpers

  get selectedMode() {
    return this.lookups?.modes.find((m) => m.code === this.form.value.dispatch_mode) ?? null;
  }

  get direction(): 'charge' | 'discharge' | 'none' {
    const p = Number(this.form.value.p_setpoint_kw ?? 0);
    return p > 0 ? 'charge' : p < 0 ? 'discharge' : 'none';
  }

  get netEnergy(): number {
    return Number(this.form.value.import_kwh ?? 0) - Number(this.form.value.export_kwh ?? 0);
  }

  get durationMin(): number | null {
    const { effective_from: from, effective_to: to } = this.form.getRawValue();
    return from && to && to >= from ? Math.round((Date.parse(to) - Date.parse(from)) / 60000) : null;
  }

  /** Fill the mode's usual command and grid service into fields the user hasn't set. */
  onModeChange(): void {
    const defaults = MODE_DEFAULTS[this.form.value.dispatch_mode ?? ''];
    if (!defaults) {
      return;
    }
    const patch: Record<string, unknown> = {};
    if (!this.form.controls.command_code.dirty) {
      patch['command_code'] = defaults.command_code;
    }
    if (!this.form.controls.grid_service.dirty) {
      patch['grid_service'] = defaults.grid_service;
    }
    this.form.patchValue(patch);
  }

  /** Until the user picks a status, it follows the end time: none -> Active, set -> Completed. */
  onEndChange(): void {
    if (!this.form.controls.status.dirty) {
      this.form.patchValue({ status: this.form.value.effective_to ? 'Completed' : 'Active' });
    }
  }

  /** Revenue = (export - import) x average price; kWh x $/MWh / 1000. */
  calculateRevenue(): void {
    const price = this.form.value.avg_price_mwh;
    if (price === null || price === undefined || (price as unknown) === '') {
      this.form.controls.avg_price_mwh.markAsTouched();
      return;
    }
    const revenue = (-this.netEnergy * Number(price)) / 1000;
    this.form.patchValue({ revenue_usd: Math.round(revenue * 100) / 100 });
  }

  invalid(name: string): boolean {
    const control = this.form.get(name);
    return !!control && control.invalid && control.touched;
  }

  groupError(key: string): boolean {
    return !!this.form.errors?.[key] && (this.form.touched || this.form.dirty);
  }

  // ---------------------------------------------------------------- save

  submit(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }
    const v = this.form.getRawValue();
    const num = (x: number | null | undefined) => (x === null || x === undefined || (x as unknown) === '' ? null : Number(x));
    const payload: DispatchEventInput = {
      dispatch_id: this.isEditMode ? undefined : text(v.dispatch_id),
      ems_id: v.ems_id!,
      dispatch_mode: v.dispatch_mode!,
      command_code: v.command_code!,
      grid_service: v.grid_service || 'NONE',
      source: text(v.source),
      issued_at: toApi(v.issued_at),
      effective_from: toApi(v.effective_from)!,
      effective_to: toApi(v.effective_to),
      status: v.status,
      p_setpoint_kw: num(v.p_setpoint_kw) ?? 0,
      ramp_rate_kw_s: num(v.ramp_rate_kw_s),
      target_soc_pct: num(v.target_soc_pct),
      soc_start_pct: num(v.soc_start_pct),
      soc_end_pct: num(v.soc_end_pct),
      import_kwh: num(v.import_kwh) ?? 0,
      export_kwh: num(v.export_kwh) ?? 0,
      avg_price_mwh: num(v.avg_price_mwh),
      revenue_usd: num(v.revenue_usd),
      accepted: !!v.accepted,
      note: text(v.note)
    };

    this.saving = true;
    this.error = null;
    const request$ =
      this.isEditMode && this.dispatchId ? this.service.update(this.dispatchId, payload) : this.service.create(payload);
    request$.subscribe({
      next: (d) => {
        this.saving = false;
        this.router.navigate(['/telemetry/dispatch', d.dispatch_id]);
      },
      error: (err) => {
        this.saving = false;
        const detail = err?.error?.detail;
        this.error = Array.isArray(detail)
          ? detail.map((d: { msg: string }) => d.msg.replace(/^Value error, /, '')).join('; ')
          : detail || 'Failed to save the dispatch.';
      }
    });
  }
}
