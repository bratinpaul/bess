import { CommonModule } from '@angular/common';
import { Component, OnInit, inject } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';

import { BatteryModuleInput } from '../../../core/models/battery-module.model';
import { BatteryPack } from '../../../core/models/battery-pack.model';
import { AssetLinksComponent } from '../../../shared/asset-links/asset-links.component';
import { BatteryModuleService } from '../../../core/services/battery-module.service';
import { BatteryPackService } from '../../../core/services/battery-pack.service';

@Component({
  selector: 'app-battery-module-form',
  standalone: true,
  imports: [CommonModule, ReactiveFormsModule, RouterLink, AssetLinksComponent],
  templateUrl: './battery-module-form.component.html',
  styleUrl: './battery-module-form.component.scss'
})
export class BatteryModuleFormComponent implements OnInit {
  private fb = inject(FormBuilder);

  moduleId: number | null = null;
  isEditMode = false;
  /** Saved values, for the shortcut links (the form fields may be mid-edit). */
  savedName = '';
  savedPackId: number | null = null;
  loading = false;
  saving = false;
  error: string | null = null;
  packs: BatteryPack[] = [];

  form = this.fb.group({
    pack_id: [null as number | null, [Validators.required]],
    serial_number: [''],
    chemistry: [''],
    nominal_voltage: [null as number | null],
    capacity_ah: [null as number | null],
    manufacture_date: [''],
    installation_date: [''],
    status: [''],
    cell_count: [null as number | null],
    soh_pct: [null as number | null]
  });

  constructor(
    private route: ActivatedRoute,
    private router: Router,
    private moduleService: BatteryModuleService,
    private packService: BatteryPackService
  ) {}

  ngOnInit(): void {
    const idParam = this.route.snapshot.paramMap.get('id');
    this.moduleId = idParam ? Number(idParam) : null;
    this.isEditMode = !!this.moduleId;
    this.loading = true;

    this.packService.list().subscribe({
      next: (packs) => {
        this.packs = packs;
        this.loading = false;
      },
      error: () => {
        this.error = 'Could not load battery packs.';
        this.loading = false;
      }
    });

    if (this.isEditMode && this.moduleId) {
      this.loading = true;
      this.moduleService.get(this.moduleId).subscribe({
        next: (item) => {
          this.savedName = item.serial_number ?? '';
          this.savedPackId = item.pack_id;
          this.form.patchValue({
            pack_id: item.pack_id,
            serial_number: item.serial_number ?? '',
            chemistry: item.chemistry ?? '',
            nominal_voltage: item.nominal_voltage,
            capacity_ah: item.capacity_ah,
            manufacture_date: item.manufacture_date ?? '',
            installation_date: item.installation_date ?? '',
            status: item.status ?? '',
            cell_count: item.cell_count,
            soh_pct: item.soh_pct
          });
          this.loading = false;
        },
        error: () => {
          this.error = 'Could not load battery module.';
          this.loading = false;
        }
      });
    }
  }

  submit(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }

    const raw = this.form.getRawValue();
    const payload: BatteryModuleInput = {
      pack_id: raw.pack_id!,
      serial_number: raw.serial_number || null,
      chemistry: raw.chemistry || null,
      nominal_voltage: raw.nominal_voltage,
      capacity_ah: raw.capacity_ah,
      manufacture_date: raw.manufacture_date || null,
      installation_date: raw.installation_date || null,
      status: raw.status || null,
      cell_count: raw.cell_count,
      soh_pct: raw.soh_pct
    };

    this.saving = true;
    this.error = null;

    const request$ =
      this.isEditMode && this.moduleId
        ? this.moduleService.update(this.moduleId, payload)
        : this.moduleService.create(payload);

    request$.subscribe({
      next: (item) => {
        this.saving = false;
        this.router.navigate(['/battery-modules', item.module_id]);
      },
      error: (err) => {
        this.saving = false;
        this.error = this.extractErrorMessage(err);
      }
    });
  }

  private extractErrorMessage(err: unknown): string {
    const detail = (err as { error?: { detail?: unknown } })?.error?.detail;
    if (typeof detail === 'string') {
      return detail;
    }
    if (Array.isArray(detail)) {
      const messages = detail.map((d) => (typeof d === 'string' ? d : d?.msg)).filter(Boolean);
      if (messages.length > 0) {
        return messages.join('; ');
      }
    }
    return 'Failed to save battery module.';
  }
}
