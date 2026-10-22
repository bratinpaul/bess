import { CommonModule } from '@angular/common';
import { Component, OnInit, inject } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';

import { BatteryContainer } from '../../../core/models/battery-container.model';
import { BatteryPackInput } from '../../../core/models/battery-pack.model';
import { BatteryContainerService } from '../../../core/services/battery-container.service';
import { BatteryPackService } from '../../../core/services/battery-pack.service';

@Component({
  selector: 'app-battery-pack-form',
  standalone: true,
  imports: [CommonModule, ReactiveFormsModule, RouterLink],
  templateUrl: './battery-pack-form.component.html',
  styleUrl: './battery-pack-form.component.scss'
})
export class BatteryPackFormComponent implements OnInit {
  private fb = inject(FormBuilder);

  packId: number | null = null;
  isEditMode = false;
  loading = false;
  saving = false;
  error: string | null = null;
  containers: BatteryContainer[] = [];

  form = this.fb.group({
    container_id: [null as number | null, [Validators.required]],
    pack_number: [''],
    nominal_voltage: [null as number | null],
    nominal_capacity_ah: [null as number | null],
    status: [''],
    module_count: [null as number | null]
  });

  constructor(
    private route: ActivatedRoute,
    private router: Router,
    private packService: BatteryPackService,
    private containerService: BatteryContainerService
  ) {}

  ngOnInit(): void {
    const idParam = this.route.snapshot.paramMap.get('id');
    this.packId = idParam ? Number(idParam) : null;
    this.isEditMode = !!this.packId;
    this.loading = true;

    this.containerService.list().subscribe({
      next: (containers) => {
        this.containers = containers;
        this.loading = false;
      },
      error: () => {
        this.error = 'Could not load battery containers.';
        this.loading = false;
      }
    });

    if (this.isEditMode && this.packId) {
      this.loading = true;
      this.packService.get(this.packId).subscribe({
        next: (item) => {
          this.form.patchValue({
            container_id: item.container_id,
            pack_number: item.pack_number ?? '',
            nominal_voltage: item.nominal_voltage,
            nominal_capacity_ah: item.nominal_capacity_ah,
            status: item.status ?? '',
            module_count: item.module_count
          });
          this.loading = false;
        },
        error: () => {
          this.error = 'Could not load battery pack.';
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
    const payload: BatteryPackInput = {
      container_id: raw.container_id!,
      pack_number: raw.pack_number || null,
      nominal_voltage: raw.nominal_voltage,
      nominal_capacity_ah: raw.nominal_capacity_ah,
      status: raw.status || null,
      module_count: raw.module_count
    };

    this.saving = true;
    this.error = null;

    const request$ =
      this.isEditMode && this.packId
        ? this.packService.update(this.packId, payload)
        : this.packService.create(payload);

    request$.subscribe({
      next: (item) => {
        this.saving = false;
        this.router.navigate(['/battery-packs', item.pack_id]);
      },
      error: () => {
        this.saving = false;
        this.error = 'Failed to save battery pack.';
      }
    });
  }
}
