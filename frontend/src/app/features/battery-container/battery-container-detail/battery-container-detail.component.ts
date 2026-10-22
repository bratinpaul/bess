import { CommonModule } from '@angular/common';
import { Component, OnInit } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';

import { BatteryContainer } from '../../../core/models/battery-container.model';
import { BatteryContainerService } from '../../../core/services/battery-container.service';
import { BatterySystemService } from '../../../core/services/battery-system.service';

@Component({
  selector: 'app-battery-container-detail',
  standalone: true,
  imports: [CommonModule, RouterLink],
  templateUrl: './battery-container-detail.component.html',
  styleUrl: './battery-container-detail.component.scss'
})
export class BatteryContainerDetailComponent implements OnInit {
  item: BatteryContainer | null = null;
  systemName: string | null = null;
  loading = true;
  error: string | null = null;

  constructor(
    private route: ActivatedRoute,
    private containerService: BatteryContainerService,
    private batterySystemService: BatterySystemService
  ) {}

  ngOnInit(): void {
    const id = Number(this.route.snapshot.paramMap.get('id'));
    this.containerService.get(id).subscribe({
      next: (item) => {
        this.item = item;
        this.batterySystemService.get(item.battery_system_id).subscribe({
          next: (system) => {
            this.systemName = system.system_name;
            this.loading = false;
          },
          error: () => {
            this.loading = false;
          }
        });
      },
      error: () => {
        this.error = 'Battery container not found.';
        this.loading = false;
      }
    });
  }
}
