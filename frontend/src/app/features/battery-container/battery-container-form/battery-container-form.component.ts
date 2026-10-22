import { CommonModule } from '@angular/common';
import { Component, OnInit, inject } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';

import { BatteryContainerInput } from '../../../core/models/battery-container.model';
import { BatterySystem } from '../../../core/models/battery-system.model';
import { BatteryContainerService } from '../../../core/services/battery-container.service';
import { BatterySystemService } from '../../../core/services/battery-system.service';

@Component({
  selector: 'app-battery-container-form',
  standalone: true,
  imports: [CommonModule, ReactiveFormsModule, RouterLink],
  templateUrl: './battery-container-form.component.html',
  styleUrl: './battery-container-form.component.scss'
})
export class BatteryContainerFormComponent implements OnInit {
  private fb = inject(FormBuilder);

  containerId: number | null = null;
  isEditMode = false;
  loading = false;
  saving = false;
  error: string | null = null;
  batterySystems: BatterySystem[] = [];

  form = this.fb.group({
    battery_system_id: [null as number | null, [Validators.required]],
    container_number: [''],
    manufacturer: [''],
    installation_date: [''],
    status: [''],
    container_type: [''],
    ip_rating: [''],
    fire_suppression: ['']
  });

  constructor(
    private route: ActivatedRoute,
    private router: Router,
    private containerService: BatteryContainerService,
    private batterySystemService: BatterySystemService
  ) {}

  ngOnInit(): void {
    const idParam = this.route.snapshot.paramMap.get('id');
    this.containerId = idParam ? Number(idParam) : null;
    this.isEditMode = !!this.containerId;
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

    if (this.isEditMode && this.containerId) {
      this.loading = true;
      this.containerService.get(this.containerId).subscribe({
        next: (item) => {
          this.form.patchValue({
            battery_system_id: item.battery_system_id,
            container_number: item.container_number ?? '',
            manufacturer: item.manufacturer ?? '',
            installation_date: item.installation_date ?? '',
            status: item.status ?? '',
            container_type: item.container_type ?? '',
            ip_rating: item.ip_rating ?? '',
            fire_suppression: item.fire_suppression ?? ''
          });
          this.loading = false;
        },
        error: () => {
          this.error = 'Could not load battery container.';
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
    const payload: BatteryContainerInput = {
      battery_system_id: raw.battery_system_id!,
      container_number: raw.container_number || null,
      manufacturer: raw.manufacturer || null,
      installation_date: raw.installation_date || null,
      status: raw.status || null,
      container_type: raw.container_type || null,
      ip_rating: raw.ip_rating || null,
      fire_suppression: raw.fire_suppression || null
    };

    this.saving = true;
    this.error = null;

    const request$ =
      this.isEditMode && this.containerId
        ? this.containerService.update(this.containerId, payload)
        : this.containerService.create(payload);

    request$.subscribe({
      next: (item) => {
        this.saving = false;
        this.router.navigate(['/battery-containers', item.container_id]);
      },
      error: () => {
        this.saving = false;
        this.error = 'Failed to save battery container.';
      }
    });
  }
}
