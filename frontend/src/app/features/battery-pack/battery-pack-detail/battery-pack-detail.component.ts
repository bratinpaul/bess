import { CommonModule } from '@angular/common';
import { Component, OnInit } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';

import { BatteryPack } from '../../../core/models/battery-pack.model';
import { BatteryContainerService } from '../../../core/services/battery-container.service';
import { BatteryPackService } from '../../../core/services/battery-pack.service';

@Component({
  selector: 'app-battery-pack-detail',
  standalone: true,
  imports: [CommonModule, RouterLink],
  templateUrl: './battery-pack-detail.component.html',
  styleUrl: './battery-pack-detail.component.scss'
})
export class BatteryPackDetailComponent implements OnInit {
  item: BatteryPack | null = null;
  containerNumber: string | null = null;
  loading = true;
  error: string | null = null;

  constructor(
    private route: ActivatedRoute,
    private packService: BatteryPackService,
    private containerService: BatteryContainerService
  ) {}

  ngOnInit(): void {
    const id = Number(this.route.snapshot.paramMap.get('id'));
    this.packService.get(id).subscribe({
      next: (item) => {
        this.item = item;
        this.containerService.get(item.container_id).subscribe({
          next: (container) => {
            this.containerNumber = container.container_number || String(container.container_id);
            this.loading = false;
          },
          error: () => {
            this.loading = false;
          }
        });
      },
      error: () => {
        this.error = 'Battery pack not found.';
        this.loading = false;
      }
    });
  }
}
