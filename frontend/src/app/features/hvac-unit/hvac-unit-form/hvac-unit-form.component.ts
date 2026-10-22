import { CommonModule } from '@angular/common';
import { Component, OnInit, inject } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';

import { BatterySystem } from '../../../core/models/battery-system.model';
import { HvacUnitInput } from '../../../core/models/hvac-unit.model';
import { BatterySystemService } from '../../../core/services/battery-system.service';
import { AssetLinksComponent } from '../../../shared/asset-links/asset-links.component';
import { HvacUnitService } from '../../../core/services/hvac-unit.service';

@Component({
  selector: 'app-hvac-unit-form',
  standalone: true,
  imports: [CommonModule, ReactiveFormsModule, RouterLink, AssetLinksComponent],
  templateUrl: './hvac-unit-form.component.html',
  styleUrl: './hvac-unit-form.component.scss'
})
export class HvacUnitFormComponent implements OnInit {
  private fb = inject(FormBuilder);

  itemId: number | null = null;
  isEditMode = false;
  /** Saved values, for the shortcut links (the form fields may be mid-edit). */
  savedCode = '';
  savedSystemId: number | null = null;
  loading = false;
  saving = false;
  error: string | null = null;
  batterySystems: BatterySystem[] = [];

  form = this.fb.group({
    battery_system_id: [null as number | null, [Validators.required]],
    // a code of only spaces is not a code
    hvac_code: ['', [Validators.required, Validators.maxLength(100), Validators.pattern(/\S/)]],
    manufacturer: [''],
    model: [''],
    hvac_type: [''],
    cooling_capacity_kw: [null as number | null],
    status: ['']
  });

  constructor(
    private route: ActivatedRoute,
    private router: Router,
    private service: HvacUnitService,
    private batterySystemService: BatterySystemService
  ) {}

  ngOnInit(): void {
    const idParam = this.route.snapshot.paramMap.get('id');
    this.itemId = idParam ? Number(idParam) : null;
    this.isEditMode = !!this.itemId;
    this.loading = true;

    this.batterySystemService.list().subscribe({
      next: (systems) => {
        this.batterySystems = systems;
        // with a single battery system there is nothing to choose
        if (!this.isEditMode && systems.length === 1) {
          this.form.patchValue({ battery_system_id: systems[0].battery_system_id });
        }
        this.loading = false;
      },
      error: () => {
        this.error = 'Could not load battery systems.';
        this.loading = false;
      }
    });

    if (this.isEditMode && this.itemId) {
      this.loading = true;
      this.service.get(this.itemId).subscribe({
        next: (item) => {
          this.savedCode = item.hvac_code;
          this.savedSystemId = item.battery_system_id;
          this.form.patchValue({
            battery_system_id: item.battery_system_id,
            hvac_code: item.hvac_code,
            manufacturer: item.manufacturer ?? '',
            model: item.model ?? '',
            hvac_type: item.hvac_type ?? '',
            cooling_capacity_kw: item.cooling_capacity_kw,
            status: item.status ?? ''
          });
          this.loading = false;
        },
        error: () => {
          this.error = 'Could not load HVAC unit.';
          this.loading = false;
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
    const payload: HvacUnitInput = {
      battery_system_id: raw.battery_system_id!,
      hvac_code: raw.hvac_code!.trim(),
      manufacturer: raw.manufacturer || null,
      model: raw.model || null,
      hvac_type: raw.hvac_type || null,
      cooling_capacity_kw: raw.cooling_capacity_kw,
      status: raw.status || null
    };

    this.saving = true;
    this.error = null;

    const request$ =
      this.isEditMode && this.itemId
        ? this.service.update(this.itemId, payload)
        : this.service.create(payload);

    request$.subscribe({
      next: (item) => {
        this.saving = false;
        this.router.navigate(['/hvac-units', item.hvac_id]);
      },
      error: (err) => {
        this.saving = false;
        const detail = err?.error?.detail;
        this.error = Array.isArray(detail)
          ? detail.map((d: { msg: string }) => d.msg.replace(/^Value error, /, '')).join('; ')
          : detail || 'Failed to save HVAC unit.';
      }
    });
  }
}
