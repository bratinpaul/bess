import { CommonModule } from '@angular/common';
import { Component, OnInit, inject } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';

import { BatterySystem } from '../../../core/models/battery-system.model';
import { EmsControllerInput } from '../../../core/models/ems-controller.model';
import { BatterySystemService } from '../../../core/services/battery-system.service';
import { AssetLinksComponent } from '../../../shared/asset-links/asset-links.component';
import { EmsControllerService } from '../../../core/services/ems-controller.service';

@Component({
  selector: 'app-ems-controller-form',
  standalone: true,
  imports: [CommonModule, ReactiveFormsModule, RouterLink, AssetLinksComponent],
  templateUrl: './ems-controller-form.component.html',
  styleUrl: './ems-controller-form.component.scss'
})
export class EmsControllerFormComponent implements OnInit {
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
    ems_code: ['', [Validators.required, Validators.maxLength(100), Validators.pattern(/\S/)]],
    manufacturer: [''],
    model: [''],
    firmware_version: [''],
    control_mode: ['']
  });

  constructor(
    private route: ActivatedRoute,
    private router: Router,
    private service: EmsControllerService,
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
          this.savedCode = item.ems_code;
          this.savedSystemId = item.battery_system_id;
          this.form.patchValue({
            battery_system_id: item.battery_system_id,
            ems_code: item.ems_code,
            manufacturer: item.manufacturer ?? '',
            model: item.model ?? '',
            firmware_version: item.firmware_version ?? '',
            control_mode: item.control_mode ?? ''
          });
          this.loading = false;
        },
        error: () => {
          this.error = 'Could not load EMS controller.';
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
    const payload: EmsControllerInput = {
      battery_system_id: raw.battery_system_id!,
      ems_code: raw.ems_code!.trim(),
      manufacturer: raw.manufacturer || null,
      model: raw.model || null,
      firmware_version: raw.firmware_version || null,
      control_mode: raw.control_mode || null
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
        this.router.navigate(['/ems-controllers', item.ems_id]);
      },
      error: (err) => {
        this.saving = false;
        const detail = err?.error?.detail;
        this.error = Array.isArray(detail)
          ? detail.map((d: { msg: string }) => d.msg.replace(/^Value error, /, '')).join('; ')
          : detail || 'Failed to save EMS controller.';
      }
    });
  }
}
