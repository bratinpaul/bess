import { CommonModule } from '@angular/common';
import { Component, OnInit, inject } from '@angular/core';
import { AbstractControl, FormBuilder, ReactiveFormsModule, ValidationErrors, Validators } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';

import {
  DAY_TYPE_LABELS,
  DayType,
  PRICE_LEVEL_LABELS,
  PriceLevel,
  TariffEmsOption,
  TariffPeriod,
  TariffPeriodInput
} from '../../../core/models/tariff-period.model';
import { TariffPeriodService } from '../../../core/services/tariff-period.service';
import { LEVEL_COLORS } from '../tariff-period-list/tariff-period-list.component';

const text = (v: string | null | undefined) => (v && v.trim() ? v.trim() : null);

function hoursInOrder(group: AbstractControl): ValidationErrors | null {
  const start = group.get('start_hour')?.value;
  const end = group.get('end_hour')?.value;
  return start !== null && end !== null && Number(end) <= Number(start) ? { hourOrder: true } : null;
}

function datesInOrder(group: AbstractControl): ValidationErrors | null {
  const from = group.get('valid_from')?.value;
  const to = group.get('valid_to')?.value;
  return from && to && to < from ? { dateOrder: true } : null;
}

@Component({
  selector: 'app-tariff-period-form',
  standalone: true,
  imports: [CommonModule, ReactiveFormsModule, RouterLink],
  templateUrl: './tariff-period-form.component.html',
  styleUrl: './tariff-period-form.component.scss'
})
export class TariffPeriodFormComponent implements OnInit {
  private fb = inject(FormBuilder);

  readonly levelLabels = PRICE_LEVEL_LABELS;
  readonly dayLabels = DAY_TYPE_LABELS;
  readonly levelColors = LEVEL_COLORS;
  readonly startHours = Array.from({ length: 24 }, (_, i) => i);
  readonly endHours = Array.from({ length: 24 }, (_, i) => i + 1);

  itemId: number | null = null;
  isEditMode = false;
  loading = false;
  saving = false;
  error: string | null = null;

  priceLevels: PriceLevel[] = ['SUPER_OFF_PEAK', 'OFF_PEAK', 'SHOULDER', 'SHOULDER_HIGH', 'PEAK'];
  dayTypes: DayType[] = ['ALL', 'WEEKDAY', 'WEEKEND'];
  seasons: string[] = ['ALL'];
  ems: TariffEmsOption[] = [];
  /** the other bands of the chosen scope, drawn behind the edited one on the preview */
  others: TariffPeriod[] = [];
  private all: TariffPeriod[] = [];

  form = this.fb.group(
    {
      ems_id: [null as number | null],
      band_code: ['', [Validators.required, Validators.maxLength(30), Validators.pattern(/^\s*[A-Za-z0-9_ ]*[A-Za-z0-9]+[A-Za-z0-9_ ]*\s*$/)]],
      band_name: ['', [Validators.required, Validators.maxLength(100), Validators.pattern(/\S/)]],
      price_level: [null as PriceLevel | null, [Validators.required]],
      start_hour: [0 as number | null, [Validators.required]],
      end_hour: [6 as number | null, [Validators.required]],
      day_type: ['ALL' as DayType, [Validators.required]],
      season: ['ALL', [Validators.required, Validators.maxLength(30)]],
      reference_price_mwh: [null as number | null, [Validators.min(0)]],
      valid_from: [''],
      valid_to: [''],
      note: ['', [Validators.maxLength(500)]]
    },
    { validators: [hoursInOrder, datesInOrder] }
  );

  constructor(
    private route: ActivatedRoute,
    private router: Router,
    private service: TariffPeriodService
  ) {}

  ngOnInit(): void {
    const idParam = this.route.snapshot.paramMap.get('id');
    this.itemId = idParam ? Number(idParam) : null;
    this.isEditMode = !!this.itemId;
    const emsParam = this.route.snapshot.queryParamMap.get('ems');
    if (!this.isEditMode && emsParam) {
      this.form.patchValue({ ems_id: Number(emsParam) });
    }
    let pending = this.isEditMode ? 3 : 2;
    const done = () => (this.loading = --pending > 0);
    this.loading = true;

    this.service.lookups().subscribe({
      next: (l) => {
        this.priceLevels = l.price_levels;
        this.dayTypes = l.day_types;
        this.seasons = l.seasons;
        this.ems = l.ems;
        done();
      },
      error: () => {
        this.error = 'Could not load the lookups. Is the backend running?';
        done();
      }
    });
    this.service.list().subscribe({
      next: (all) => {
        this.all = all;
        this.refreshOthers();
        done();
      },
      error: () => done()
    });
    if (this.isEditMode && this.itemId) {
      this.service.get(this.itemId).subscribe({
        next: (b) => {
          this.form.patchValue({
            ems_id: b.ems_id,
            band_code: b.band_code,
            band_name: b.band_name,
            price_level: b.price_level,
            start_hour: b.start_hour,
            end_hour: b.end_hour,
            day_type: b.day_type,
            season: b.season,
            reference_price_mwh: b.reference_price_mwh === null ? null : Number(b.reference_price_mwh),
            valid_from: b.valid_from ?? '',
            valid_to: b.valid_to ?? '',
            note: b.note ?? ''
          });
          this.refreshOthers();
          done();
        },
        error: () => {
          this.error = 'Could not load the band.';
          done();
        }
      });
    }
    this.form.valueChanges.subscribe(() => this.refreshOthers());
  }

  private refreshOthers(): void {
    const v = this.form.getRawValue();
    this.others = this.all.filter(
      (b) =>
        b.tariff_period_id !== this.itemId &&
        b.ems_id === (v.ems_id ?? null) &&
        (b.day_type === 'ALL' || v.day_type === 'ALL' || b.day_type === v.day_type) &&
        (b.season === 'ALL' || v.season === 'ALL' || b.season === v.season)
    );
  }

  /** hours of the edited band that another band of the same scope / day type / season already covers */
  get clashes(): TariffPeriod[] {
    const v = this.form.getRawValue();
    const s = Number(v.start_hour);
    const e = Number(v.end_hour);
    return this.others.filter((b) => s < b.end_hour && b.start_hour < e);
  }

  invalid(name: string): boolean {
    const control = this.form.get(name);
    return !!control && control.invalid && control.touched;
  }

  emsLabel(e: TariffEmsOption): string {
    return `${e.site_name ?? e.ems_code} · ${e.ems_code}`;
  }

  hourLabel(h: number): string {
    return `${String(h).padStart(2, '0')}:00`;
  }

  get previewLevel(): PriceLevel {
    return (this.form.getRawValue().price_level as PriceLevel) ?? 'SHOULDER';
  }

  get preview(): { start: number; end: number; code: string } {
    const v = this.form.getRawValue();
    return { start: Number(v.start_hour ?? 0), end: Number(v.end_hour ?? 0), code: (v.band_code || 'NEW').trim().toUpperCase() };
  }

  submit(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }
    const raw = this.form.getRawValue();
    const price = raw.reference_price_mwh;
    const payload: TariffPeriodInput = {
      ems_id: raw.ems_id ?? null,
      band_code: raw.band_code!.trim(),
      band_name: raw.band_name!.trim(),
      price_level: raw.price_level!,
      start_hour: Number(raw.start_hour),
      end_hour: Number(raw.end_hour),
      day_type: raw.day_type!,
      season: (raw.season || 'ALL').trim(),
      reference_price_mwh: price === null || (price as unknown) === '' ? null : Number(price),
      valid_from: raw.valid_from || null,
      valid_to: raw.valid_to || null,
      note: text(raw.note)
    };
    this.saving = true;
    this.error = null;
    const request$ =
      this.isEditMode && this.itemId ? this.service.update(this.itemId, payload) : this.service.create(payload);
    request$.subscribe({
      next: () => {
        this.saving = false;
        this.router.navigate(['/tariff-bands']);
      },
      error: (err) => {
        this.saving = false;
        const detail = err?.error?.detail;
        this.error = Array.isArray(detail)
          ? detail.map((d: { msg: string }) => d.msg.replace(/^Value error, /, '')).join('; ')
          : detail || 'Failed to save the band.';
      }
    });
  }
}
