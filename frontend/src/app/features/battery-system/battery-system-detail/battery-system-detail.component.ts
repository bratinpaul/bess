import { CommonModule } from '@angular/common';
import { Component, OnInit } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';

import { BatterySystem } from '../../../core/models/battery-system.model';
import { AssetLinksComponent } from '../../../shared/asset-links/asset-links.component';
import { BatterySystemService } from '../../../core/services/battery-system.service';
import { SiteService } from '../../../core/services/site.service';

@Component({
  selector: 'app-battery-system-detail',
  standalone: true,
  imports: [CommonModule, RouterLink, AssetLinksComponent],
  templateUrl: './battery-system-detail.component.html',
  styleUrl: './battery-system-detail.component.scss'
})
export class BatterySystemDetailComponent implements OnInit {
  item: BatterySystem | null = null;
  siteName: string | null = null;
  loading = true;
  error: string | null = null;

  constructor(
    private route: ActivatedRoute,
    private batterySystemService: BatterySystemService,
    private siteService: SiteService
  ) {}

  ngOnInit(): void {
    const id = Number(this.route.snapshot.paramMap.get('id'));
    this.batterySystemService.get(id).subscribe({
      next: (item) => {
        this.item = item;
        this.siteService.get(item.site_id).subscribe({
          next: (site) => {
            this.siteName = site.site_name;
            this.loading = false;
          },
          error: () => {
            this.loading = false;
          }
        });
      },
      error: () => {
        this.error = 'Battery system not found.';
        this.loading = false;
      }
    });
  }
}
