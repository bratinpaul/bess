import { CommonModule } from '@angular/common';
import { Component, OnInit } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';

import { EmsController } from '../../../core/models/ems-controller.model';
import { AssetLinksComponent } from '../../../shared/asset-links/asset-links.component';
import { EmsControllerService } from '../../../core/services/ems-controller.service';

@Component({
  selector: 'app-ems-controller-detail',
  standalone: true,
  imports: [CommonModule, RouterLink, AssetLinksComponent],
  templateUrl: './ems-controller-detail.component.html',
  styleUrl: './ems-controller-detail.component.scss'
})
export class EmsControllerDetailComponent implements OnInit {
  item: EmsController | null = null;
  loading = true;
  error: string | null = null;

  constructor(
    private route: ActivatedRoute,
    private service: EmsControllerService
  ) {}

  ngOnInit(): void {
    const id = Number(this.route.snapshot.paramMap.get('id'));
    this.service.get(id).subscribe({
      next: (item) => {
        this.item = item;
        this.loading = false;
      },
      error: () => {
        this.error = 'EMS Controller not found.';
        this.loading = false;
      }
    });
  }
}
