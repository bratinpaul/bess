import { CommonModule } from '@angular/common';
import { Component, OnInit, inject } from '@angular/core';
import { AbstractControl, FormBuilder, ReactiveFormsModule, ValidationErrors, Validators } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';

import { ALARM_SOURCES, AlarmSource } from '../../../../core/models/alarm-catalog.model';
import {
  AlarmEventInput,
  AlarmEventLookups,
  LINKED_ASSET_LABELS,
  LinkedAssetType
} from '../../../../core/models/alarm-event.model';
import { AlarmEventService } from '../../../../core/services/alarm-event.service';

const text = (v: string | null | undefined) => (v && v.trim() ? v.trim() : null);
/** API time -> datetime-local value, keeping plant time ("2026-08-01T15:50:00+05:30" -> "2026-08-01T15:50"). */
const toInput = (iso: string | null) => (iso ? iso.slice(0, 16) : '');
/** datetime-local value -> API time; no zone, so the server reads it as plant time. */
const toApi = (value: string | null | undefined) => (value ? `${value}:00` : null);

/** Catalog asset types -> the master-data table to pick the asset from. */
const CATALOG_ASSET_TYPES: Record<string, LinkedAssetType> = {
  system: 'battery_system',
  pack: 'battery_pack',
  module: 'battery_module',
  cell: 'battery_module',
  inverter: 'pcs',
  'site controller': 'ems_controller',
  'hvac unit': 'hvac_unit'
};

function timesValidator(group: AbstractControl): ValidationErrors | null {
  const v = group.value;
  const errors: ValidationErrors = {};
  if (v.start_time && v.end_time && v.end_time < v.start_time) {
    errors['endBeforeStart'] = true;
  }
  if (!!text(v.acknowledged_by) !== !!v.acknowledged_at) {
    errors['ackPair'] = true;
  }
  if (v.start_time && v.acknowledged_at && v.acknowledged_at < v.start_time) {
    errors['ackBeforeStart'] = true;
  }
  return Object.keys(errors).length ? errors : null;
}

@Component({
  selector: 'app-alarm-event-form',
  standalone: true,
  imports: [CommonModule, ReactiveFormsModule, RouterLink],
  templateUrl: './alarm-event-form.component.html',
  styleUrl: './alarm-event-form.component.scss'
})
export class AlarmEventFormComponent implements OnInit {
  private fb = inject(FormBuilder);

  alarmId: string | null = null;
  isEditMode = false;
  loading = true;
  saving = false;
  error: string | null = null;

  lookups: AlarmEventLookups | null = null;
  sources = ALARM_SOURCES;
  assetTypes = Object.keys(LINKED_ASSET_LABELS) as LinkedAssetType[];
  assetLabels = LINKED_ASSET_LABELS;

  form = this.fb.group(
    {
      alarm_id: ['', [Validators.required, Validators.maxLength(50), Validators.pattern(/\S/)]],
      source: [null as AlarmSource | null, [Validators.required]],
      alarm_catalog_id: [null as number | null, [Validators.required]],
      severity_level: [null as number | null, [Validators.required]],
      start_time: ['', [Validators.required]],
      end_time: [''],
      linked_asset_type: [null as LinkedAssetType | null],
      linked_asset_id: [null as number | null],
      trigger_value: [null as number | null],
      threshold_value: [null as number | null],
      unit: ['', [Validators.maxLength(20)]],
      acknowledged_by: ['', [Validators.maxLength(100)]],
      acknowledged_at: ['']
    },
    { validators: [timesValidator] }
  );

  constructor(
    private route: ActivatedRoute,
    private router: Router,
    private service: AlarmEventService
  ) {}

  ngOnInit(): void {
    this.alarmId = this.route.snapshot.paramMap.get('alarmId');
    this.isEditMode = !!this.alarmId;
    let pending = 2;
    const done = () => (this.loading = --pending > 0);

    this.service.lookups().subscribe({
      next: (lookups) => {
        this.lookups = lookups;
        done();
      },
      error: () => {
        this.error = 'Could not load the alarm catalog and assets.';
        done();
      }
    });

    if (this.isEditMode && this.alarmId) {
      this.form.controls.alarm_id.disable();
      this.service.get(this.alarmId).subscribe({
        next: (a) => {
          this.form.patchValue({
            alarm_id: a.alarm_id,
            source: a.source,
            alarm_catalog_id: a.alarm_catalog_id,
            severity_level: a.severity_level,
            start_time: toInput(a.start_time),
            end_time: toInput(a.end_time),
            linked_asset_type: a.linked_asset_type,
            linked_asset_id: a.linked_asset_id,
            trigger_value: a.trigger_value === null ? null : Number(a.trigger_value),
            threshold_value: a.threshold_value === null ? null : Number(a.threshold_value),
            unit: a.unit ?? '',
            acknowledged_by: a.acknowledged_by ?? '',
            acknowledged_at: toInput(a.acknowledged_at)
          });
          done();
        },
        error: () => {
          this.error = `Could not load alarm ${this.alarmId}.`;
          done();
        }
      });
    } else {
      this.service.nextId().subscribe({
        next: (id) => {
          this.form.patchValue({ alarm_id: id });
          done();
        },
        error: () => done()
      });
    }
  }

  // ---------------------------------------------------------------- options

  get catalogOptions() {
    const source = this.form.value.source;
    return (this.lookups?.catalog ?? []).filter((c) => !source || c.source === source);
  }

  get assetOptions() {
    const type = this.form.value.linked_asset_type;
    return (this.lookups?.assets ?? []).filter((a) => a.asset_type === type);
  }

  get selectedCatalog() {
    return this.lookups?.catalog.find((c) => c.alarm_catalog_id === this.form.value.alarm_catalog_id) ?? null;
  }

  onSourceChange(): void {
    // the chosen alarm must belong to the new source
    if (this.selectedCatalog && this.selectedCatalog.source !== this.form.value.source) {
      this.form.patchValue({ alarm_catalog_id: null });
    }
  }

  /** Fill the catalog's defaults into fields the user hasn't set yet. */
  onAlarmChange(): void {
    const c = this.selectedCatalog;
    if (!c) {
      return;
    }
    const v = this.form.getRawValue();
    const patch: Record<string, unknown> = {};
    if (!this.form.controls.severity_level.dirty || v.severity_level === null) {
      patch['severity_level'] = c.severity_level;
    }
    if (v.threshold_value === null && c.threshold !== null) {
      patch['threshold_value'] = Number(c.threshold);
    }
    if (!text(v.unit) && c.unit) {
      patch['unit'] = c.unit;
    }
    const assetType = CATALOG_ASSET_TYPES[(c.asset_type ?? '').toLowerCase()];
    if (!v.linked_asset_type && assetType) {
      patch['linked_asset_type'] = assetType;
      const options = (this.lookups?.assets ?? []).filter((a) => a.asset_type === assetType);
      if (options.length === 1) {
        patch['linked_asset_id'] = options[0].asset_id;
      }
    }
    this.form.patchValue(patch);
  }

  onAssetTypeChange(): void {
    const options = this.assetOptions;
    this.form.patchValue({ linked_asset_id: options.length === 1 ? options[0].asset_id : null });
  }

  acknowledgeNow(): void {
    const now = new Date();
    const pad = (n: number) => String(n).padStart(2, '0');
    const local = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}T${pad(now.getHours())}:${pad(now.getMinutes())}`;
    this.form.patchValue({ acknowledged_at: local });
    this.form.controls.acknowledged_at.markAsTouched();
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
    const num = (x: number | null) => (x === null || (x as unknown) === '' ? null : Number(x));
    const payload: AlarmEventInput = {
      alarm_id: this.isEditMode ? undefined : text(v.alarm_id),
      start_time: toApi(v.start_time)!,
      end_time: toApi(v.end_time),
      alarm_catalog_id: v.alarm_catalog_id!,
      severity_level: v.severity_level,
      // the API names a linked asset after its master-data record
      asset_type: null,
      asset_code: null,
      linked_asset_type: v.linked_asset_type || null,
      linked_asset_id: v.linked_asset_type ? v.linked_asset_id : null,
      trigger_value: num(v.trigger_value),
      threshold_value: num(v.threshold_value),
      unit: text(v.unit),
      acknowledged_by: text(v.acknowledged_by),
      acknowledged_at: toApi(v.acknowledged_at)
    };
    if (payload.linked_asset_type && payload.linked_asset_id === null) {
      this.form.controls.linked_asset_id.setErrors({ required: true });
      this.form.controls.linked_asset_id.markAsTouched();
      return;
    }

    this.saving = true;
    this.error = null;
    const request$ =
      this.isEditMode && this.alarmId ? this.service.update(this.alarmId, payload) : this.service.create(payload);
    request$.subscribe({
      next: (a) => {
        this.saving = false;
        this.router.navigate(['/telemetry/alarms', a.alarm_id]);
      },
      error: (err) => {
        this.saving = false;
        const detail = err?.error?.detail;
        this.error = Array.isArray(detail)
          ? detail.map((d: { msg: string }) => d.msg.replace(/^Value error, /, '')).join('; ')
          : detail || 'Failed to save the alarm.';
      }
    });
  }
}
