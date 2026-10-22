import { CommonModule } from '@angular/common';
import { Component, OnInit, inject } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';

import {
  ALARM_SOURCES,
  AlarmCatalogInput,
  AlarmSeverity,
  AlarmSource
} from '../../../core/models/alarm-catalog.model';
import { AlarmCatalogService } from '../../../core/services/alarm-catalog.service';

const text = (v: string | null | undefined) => (v && v.trim() ? v.trim() : null);

@Component({
  selector: 'app-alarm-catalog-form',
  standalone: true,
  imports: [CommonModule, ReactiveFormsModule, RouterLink],
  templateUrl: './alarm-catalog-form.component.html',
  styleUrl: './alarm-catalog-form.component.scss'
})
export class AlarmCatalogFormComponent implements OnInit {
  private fb = inject(FormBuilder);

  itemId: number | null = null;
  isEditMode = false;
  loading = false;
  saving = false;
  error: string | null = null;

  sources = ALARM_SOURCES;
  severities: AlarmSeverity[] = [];
  alarmTypes: string[] = [];
  assetTypes: string[] = [];

  form = this.fb.group({
    source: [null as AlarmSource | null, [Validators.required]],
    // a value of only spaces is not a value
    alarm_code: ['', [Validators.required, Validators.maxLength(100), Validators.pattern(/\S/)]],
    alarm_type: ['', [Validators.required, Validators.maxLength(50), Validators.pattern(/\S/)]],
    severity_level: [null as number | null, [Validators.required]],
    asset_type: ['', [Validators.maxLength(50)]],
    description: ['', [Validators.required, Validators.maxLength(500), Validators.pattern(/\S/)]],
    probable_cause: ['', [Validators.maxLength(500)]],
    threshold: [null as number | null],
    unit: ['', [Validators.maxLength(20)]]
  });

  constructor(
    private route: ActivatedRoute,
    private router: Router,
    private service: AlarmCatalogService
  ) {}

  ngOnInit(): void {
    const idParam = this.route.snapshot.paramMap.get('id');
    this.itemId = idParam ? Number(idParam) : null;
    this.isEditMode = !!this.itemId;
    // lookups and (in edit mode) the entry load in parallel
    let pending = this.isEditMode ? 2 : 1;
    const done = () => (this.loading = --pending > 0);
    this.loading = true;

    this.service.lookups().subscribe({
      next: (lookups) => {
        this.severities = lookups.severities;
        this.alarmTypes = lookups.alarm_types;
        this.assetTypes = lookups.asset_types;
        done();
      },
      error: () => {
        this.error = 'Could not load severities.';
        done();
      }
    });

    if (this.isEditMode && this.itemId) {
      this.service.get(this.itemId).subscribe({
        next: (item) => {
          this.form.patchValue({
            source: item.source,
            alarm_code: item.alarm_code,
            alarm_type: item.alarm_type,
            severity_level: item.severity_level,
            asset_type: item.asset_type ?? '',
            description: item.description,
            probable_cause: item.probable_cause ?? '',
            threshold: item.threshold === null ? null : Number(item.threshold),
            unit: item.unit ?? ''
          });
          done();
        },
        error: () => {
          this.error = 'Could not load the alarm.';
          done();
        }
      });
    }
  }

  invalid(name: string): boolean {
    const control = this.form.get(name);
    return !!control && control.invalid && control.touched;
  }

  submit(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }
    const raw = this.form.getRawValue();
    const payload: AlarmCatalogInput = {
      source: raw.source!,
      alarm_code: raw.alarm_code!.trim(),
      alarm_type: raw.alarm_type!.trim(),
      severity_level: raw.severity_level!,
      asset_type: text(raw.asset_type),
      description: raw.description!.trim(),
      probable_cause: text(raw.probable_cause),
      threshold: raw.threshold === null || (raw.threshold as unknown) === '' ? null : raw.threshold,
      unit: text(raw.unit)
    };

    this.saving = true;
    this.error = null;
    const request$ =
      this.isEditMode && this.itemId ? this.service.update(this.itemId, payload) : this.service.create(payload);
    request$.subscribe({
      next: (item) => {
        this.saving = false;
        this.router.navigate(['/alarm-catalog', item.alarm_catalog_id]);
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
