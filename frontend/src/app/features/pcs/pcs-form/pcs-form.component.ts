import { CommonModule } from '@angular/common';
import { Component, OnInit, inject } from '@angular/core';
import { AbstractControl, FormBuilder, ReactiveFormsModule, ValidationErrors, Validators } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';

import { BatterySystem } from '../../../core/models/battery-system.model';
import { PcsInput } from '../../../core/models/pcs.model';
import { BatterySystemService } from '../../../core/services/battery-system.service';
import { AssetLinksComponent } from '../../../shared/asset-links/asset-links.component';
import { PcsService } from '../../../core/services/pcs.service';

function greaterThanZero(control: AbstractControl): ValidationErrors | null {
  const value = control.value;
  if (value === null || value === '' || value === undefined) {
    return null;
  }
  return Number(value) > 0 ? null : { greaterThanZero: true };
}

@Component({
  selector: 'app-pcs-form',
  standalone: true,
  imports: [CommonModule, ReactiveFormsModule, RouterLink, AssetLinksComponent],
  templateUrl: './pcs-form.component.html',
  styleUrl: './pcs-form.component.scss'
})
export class PcsFormComponent implements OnInit {
  private fb = inject(FormBuilder);

  pcsId: number | null = null;
  isEditMode = false;
  /** Saved code, for the shortcut links (the form field may be mid-edit). */
  savedCode = '';
  loading = false;
  saving = false;
  error: string | null = null;
  batterySystems: BatterySystem[] = [];

  form = this.fb.group({
    system_id: [null as number | null, [Validators.required]],
    pcs_code: ['', [Validators.required, Validators.maxLength(50)]],
    manufacturer: [''],
    model: [''],
    serial_number: [''],
    topology: [''],
    cooling: [''],
    rated_power_kw: [null as number | null, [Validators.required, greaterThanZero]],
    rated_apparent_kva: [null as number | null],
    max_charge_kw: [null as number | null],
    max_discharge_kw: [null as number | null],
    rated_ac_voltage_v: [null as number | null, [Validators.required]],
    ac_frequency_hz: [50.0 as number | null],
    phases: [3],
    dc_voltage_min_v: [null as number | null],
    dc_voltage_max_v: [null as number | null],
    dc_voltage_nom_v: [null as number | null],
    min_power_factor: [null as number | null],
    grid_code: [''],
    firmware: [''],
    commissioned_on: [''],
    efficiency_pct: [null as number | null],
    grid_mode: ['']
  });

  constructor(
    private route: ActivatedRoute,
    private router: Router,
    private pcsService: PcsService,
    private batterySystemService: BatterySystemService
  ) {}

  ngOnInit(): void {
    const idParam = this.route.snapshot.paramMap.get('id');
    this.pcsId = idParam ? Number(idParam) : null;
    this.isEditMode = this.pcsId !== null;
    this.loading = true;

    this.batterySystemService.list().subscribe({
      next: (systems) => {
        this.batterySystems = systems;
        this.loading = false;
      },
      error: () => {
        this.error = 'Could not load battery systems.';
        this.loading = false;
      }
    });

    if (this.isEditMode && this.pcsId !== null) {
      this.loading = true;
      this.pcsService.get(this.pcsId).subscribe({
        next: (item) => {
          this.savedCode = item.pcs_code;
          this.form.patchValue({
            system_id: item.system_id,
            pcs_code: item.pcs_code,
            manufacturer: item.manufacturer ?? '',
            model: item.model ?? '',
            serial_number: item.serial_number ?? '',
            topology: item.topology ?? '',
            cooling: item.cooling ?? '',
            rated_power_kw: item.rated_power_kw,
            rated_apparent_kva: item.rated_apparent_kva,
            max_charge_kw: item.max_charge_kw,
            max_discharge_kw: item.max_discharge_kw,
            rated_ac_voltage_v: item.rated_ac_voltage_v,
            ac_frequency_hz: item.ac_frequency_hz,
            phases: item.phases,
            dc_voltage_min_v: item.dc_voltage_min_v,
            dc_voltage_max_v: item.dc_voltage_max_v,
            dc_voltage_nom_v: item.dc_voltage_nom_v,
            min_power_factor: item.min_power_factor,
            grid_code: item.grid_code ?? '',
            firmware: item.firmware ?? '',
            commissioned_on: item.commissioned_on ?? '',
            efficiency_pct: item.efficiency_pct,
            grid_mode: item.grid_mode ?? ''
          });
          this.loading = false;
        },
        error: () => {
          this.error = 'Could not load PCS.';
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
    const payload: PcsInput = {
      system_id: raw.system_id!,
      pcs_code: raw.pcs_code!,
      manufacturer: raw.manufacturer || null,
      model: raw.model || null,
      serial_number: raw.serial_number || null,
      topology: raw.topology || null,
      cooling: raw.cooling || null,
      rated_power_kw: raw.rated_power_kw,
      rated_apparent_kva: raw.rated_apparent_kva,
      max_charge_kw: raw.max_charge_kw,
      max_discharge_kw: raw.max_discharge_kw,
      rated_ac_voltage_v: raw.rated_ac_voltage_v,
      ac_frequency_hz: raw.ac_frequency_hz,
      phases: Number(raw.phases),
      dc_voltage_min_v: raw.dc_voltage_min_v,
      dc_voltage_max_v: raw.dc_voltage_max_v,
      dc_voltage_nom_v: raw.dc_voltage_nom_v,
      min_power_factor: raw.min_power_factor,
      grid_code: raw.grid_code || null,
      firmware: raw.firmware || null,
      commissioned_on: raw.commissioned_on || null,
      efficiency_pct: raw.efficiency_pct,
      grid_mode: raw.grid_mode || null
    };

    this.saving = true;
    this.error = null;

    const request$ =
      this.isEditMode && this.pcsId !== null
        ? this.pcsService.update(this.pcsId, payload)
        : this.pcsService.create(payload);

    request$.subscribe({
      next: (item) => {
        this.saving = false;
        this.router.navigate(['/pcs', item.pcs_id]);
      },
      error: (err) => {
        this.saving = false;
        this.error = err?.error?.detail || 'Failed to save PCS.';
      }
    });
  }
}
