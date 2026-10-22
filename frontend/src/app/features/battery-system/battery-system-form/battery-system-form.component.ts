import { CommonModule } from '@angular/common';
import { Component, OnInit, inject } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { forkJoin } from 'rxjs';

import { BatteryChemistry, BatterySystemInput } from '../../../core/models/battery-system.model';
import { Site } from '../../../core/models/site.model';
import { BatteryChemistryService } from '../../../core/services/battery-chemistry.service';
import { AssetLinksComponent } from '../../../shared/asset-links/asset-links.component';
import { BatterySystemService } from '../../../core/services/battery-system.service';
import { SiteService } from '../../../core/services/site.service';

@Component({
  selector: 'app-battery-system-form',
  standalone: true,
  imports: [CommonModule, ReactiveFormsModule, RouterLink, AssetLinksComponent],
  templateUrl: './battery-system-form.component.html',
  styleUrl: './battery-system-form.component.scss'
})
export class BatterySystemFormComponent implements OnInit {
  private fb = inject(FormBuilder);

  batterySystemId: number | null = null;
  isEditMode = false;
  /** Saved name, for the shortcut links (the form field may be mid-edit). */
  savedName = '';
  loading = false;
  saving = false;
  error: string | null = null;
  sites: Site[] = [];
  chemistries: BatteryChemistry[] = [];

  form = this.fb.group({
    site_id: [null as number | null, [Validators.required]],
    system_name: ['', [Validators.required, Validators.maxLength(100)]],
    manufacturer: [''],
    model: [''],
    chemistry_code: ['', [Validators.required]],
    series_cells: [null as number | null, [Validators.required, Validators.min(1)]],
    parallel_cells: [null as number | null, [Validators.required, Validators.min(1)]],
    commissioned_on: [''],
    bms_firmware: [''],
    rated_power_mw: [null as number | null],
    rated_energy_mwh: [null as number | null],
    nominal_dc_voltage: [null as number | null],
    status: ['']
  });

  constructor(
    private route: ActivatedRoute,
    private router: Router,
    private batterySystemService: BatterySystemService,
    private siteService: SiteService,
    private batteryChemistryService: BatteryChemistryService
  ) {}

  ngOnInit(): void {
    const idParam = this.route.snapshot.paramMap.get('id');
    this.batterySystemId = idParam ? Number(idParam) : null;
    this.isEditMode = !!this.batterySystemId;
    this.loading = true;

    forkJoin({
      sites: this.siteService.list(),
      chemistries: this.batteryChemistryService.list()
    }).subscribe({
      next: ({ sites, chemistries }) => {
        this.sites = sites;
        this.chemistries = chemistries;
        this.loading = false;
      },
      error: () => {
        this.error = 'Could not load sites or chemistries.';
        this.loading = false;
      }
    });

    if (this.isEditMode && this.batterySystemId) {
      this.loading = true;
      this.batterySystemService.get(this.batterySystemId).subscribe({
        next: (item) => {
          this.savedName = item.system_name;
          this.form.patchValue({
            site_id: item.site_id,
            system_name: item.system_name,
            manufacturer: item.manufacturer ?? '',
            model: item.model ?? '',
            chemistry_code: item.chemistry_code,
            series_cells: item.series_cells,
            parallel_cells: item.parallel_cells,
            commissioned_on: item.commissioned_on ?? '',
            bms_firmware: item.bms_firmware ?? '',
            rated_power_mw: item.rated_power_mw,
            rated_energy_mwh: item.rated_energy_mwh,
            nominal_dc_voltage: item.nominal_dc_voltage,
            status: item.status ?? ''
          });
          this.loading = false;
        },
        error: () => {
          this.error = 'Could not load battery system.';
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
    const payload: BatterySystemInput = {
      site_id: raw.site_id!,
      system_name: raw.system_name!,
      manufacturer: raw.manufacturer || null,
      model: raw.model || null,
      chemistry_code: raw.chemistry_code!,
      series_cells: raw.series_cells!,
      parallel_cells: raw.parallel_cells!,
      commissioned_on: raw.commissioned_on || null,
      bms_firmware: raw.bms_firmware || null,
      rated_power_mw: raw.rated_power_mw,
      rated_energy_mwh: raw.rated_energy_mwh,
      nominal_dc_voltage: raw.nominal_dc_voltage,
      status: raw.status || null
    };

    this.saving = true;
    this.error = null;

    const request$ =
      this.isEditMode && this.batterySystemId
        ? this.batterySystemService.update(this.batterySystemId, payload)
        : this.batterySystemService.create(payload);

    request$.subscribe({
      next: (item) => {
        this.saving = false;
        this.router.navigate(['/battery-systems', item.battery_system_id]);
      },
      error: () => {
        this.saving = false;
        this.error = 'Failed to save battery system.';
      }
    });
  }
}
