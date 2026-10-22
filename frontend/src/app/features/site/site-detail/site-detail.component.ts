import { CommonModule } from '@angular/common';
import { Component, OnInit } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';

import { Site } from '../../../core/models/site.model';
import { SiteService } from '../../../core/services/site.service';
import { HasPermissionDirective } from '../../../core/auth/has-permission.directive';

@Component({
  selector: 'app-site-detail',
  standalone: true,
  imports: [CommonModule, RouterLink, HasPermissionDirective],
  templateUrl: './site-detail.component.html',
  styleUrl: './site-detail.component.scss'
})
export class SiteDetailComponent implements OnInit {
  site: Site | null = null;
  loading = true;
  error: string | null = null;

  constructor(private route: ActivatedRoute, private siteService: SiteService) {}

  ngOnInit(): void {
    const siteId = Number(this.route.snapshot.paramMap.get('id'));
    this.siteService.get(siteId).subscribe({
      next: (site) => {
        this.site = site;
        this.loading = false;
      },
      error: () => {
        this.error = 'Site not found.';
        this.loading = false;
      }
    });
  }
}
