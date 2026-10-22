import { CommonModule } from '@angular/common';
import { Component, OnInit } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';

import { HvacUnit } from '../../../core/models/hvac-unit.model';
import { AssetLinksComponent } from '../../../shared/asset-links/asset-links.component';
import { HvacUnitService } from '../../../core/services/hvac-unit.service';

@Component({
  selector: 'app-hvac-unit-detail',
  standalone: true,
  imports: [CommonModule, RouterLink, AssetLinksComponent],
  templateUrl: './hvac-unit-detail.component.html',
  styleUrl: './hvac-unit-detail.component.scss'
})
export class HvacUnitDetailComponent implements OnInit {
  item: HvacUnit | null = null;
  loading = true;
  error: string | null = null;

  constructor(
    private route: ActivatedRoute,
    private service: HvacUnitService
  ) {}

  ngOnInit(): void {
    const id = Number(this.route.snapshot.paramMap.get('id'));
    this.service.get(id).subscribe({
      next: (item) => {
        this.item = item;
        this.loading = false;
      },
      error: () => {
        this.error = 'HVAC Unit not found.';
        this.loading = false;
      }
    });
  }
}
