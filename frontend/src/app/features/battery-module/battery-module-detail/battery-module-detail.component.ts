import { CommonModule } from '@angular/common';
import { Component, OnInit } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';

import { BatteryModule } from '../../../core/models/battery-module.model';
import { AssetLinksComponent } from '../../../shared/asset-links/asset-links.component';
import { BatteryModuleService } from '../../../core/services/battery-module.service';
import { BatteryPackService } from '../../../core/services/battery-pack.service';

@Component({
  selector: 'app-battery-module-detail',
  standalone: true,
  imports: [CommonModule, RouterLink, AssetLinksComponent],
  templateUrl: './battery-module-detail.component.html',
  styleUrl: './battery-module-detail.component.scss'
})
export class BatteryModuleDetailComponent implements OnInit {
  item: BatteryModule | null = null;
  packNumber: string | null = null;
  loading = true;
  error: string | null = null;

  constructor(
    private route: ActivatedRoute,
    private moduleService: BatteryModuleService,
    private packService: BatteryPackService
  ) {}

  ngOnInit(): void {
    const id = Number(this.route.snapshot.paramMap.get('id'));
    this.moduleService.get(id).subscribe({
      next: (item) => {
        this.item = item;
        this.packService.get(item.pack_id).subscribe({
          next: (pack) => {
            this.packNumber = pack.pack_number || String(pack.pack_id);
            this.loading = false;
          },
          error: () => {
            this.loading = false;
          }
        });
      },
      error: () => {
        this.error = 'Battery module not found.';
        this.loading = false;
      }
    });
  }
}
