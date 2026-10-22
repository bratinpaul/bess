import { CommonModule } from '@angular/common';
import { Component, OnInit } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';

import { Pcs } from '../../../core/models/pcs.model';
import { BatterySystemService } from '../../../core/services/battery-system.service';
import { AssetLinksComponent } from '../../../shared/asset-links/asset-links.component';
import { PcsService } from '../../../core/services/pcs.service';

@Component({
  selector: 'app-pcs-detail',
  standalone: true,
  imports: [CommonModule, RouterLink, AssetLinksComponent],
  templateUrl: './pcs-detail.component.html',
  styleUrl: './pcs-detail.component.scss'
})
export class PcsDetailComponent implements OnInit {
  item: Pcs | null = null;
  systemName: string | null = null;
  loading = true;
  error: string | null = null;

  constructor(
    private route: ActivatedRoute,
    private pcsService: PcsService,
    private batterySystemService: BatterySystemService
  ) {}

  ngOnInit(): void {
    const id = Number(this.route.snapshot.paramMap.get('id'));
    this.pcsService.get(id).subscribe({
      next: (item) => {
        this.item = item;
        this.batterySystemService.get(item.system_id).subscribe({
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
        this.error = 'PCS not found.';
        this.loading = false;
      }
    });
  }
}
