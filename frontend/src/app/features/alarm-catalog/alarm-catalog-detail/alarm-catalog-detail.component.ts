import { CommonModule } from '@angular/common';
import { Component, OnInit } from '@angular/core';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';

import { AlarmCatalogEntry } from '../../../core/models/alarm-catalog.model';
import { AlarmCatalogService } from '../../../core/services/alarm-catalog.service';

@Component({
  selector: 'app-alarm-catalog-detail',
  standalone: true,
  imports: [CommonModule, RouterLink],
  templateUrl: './alarm-catalog-detail.component.html',
  styleUrl: './alarm-catalog-detail.component.scss'
})
export class AlarmCatalogDetailComponent implements OnInit {
  item: AlarmCatalogEntry | null = null;
  loading = true;
  error: string | null = null;

  confirmDelete = false;
  deleting = false;
  deleteError: string | null = null;

  constructor(
    private route: ActivatedRoute,
    private router: Router,
    private service: AlarmCatalogService
  ) {}

  ngOnInit(): void {
    const id = Number(this.route.snapshot.paramMap.get('id'));
    this.service.get(id).subscribe({
      next: (item) => {
        this.item = item;
        this.loading = false;
      },
      error: () => {
        this.error = 'Alarm catalog entry not found.';
        this.loading = false;
      }
    });
  }

  deleteConfirmed(): void {
    if (!this.item) {
      return;
    }
    this.deleting = true;
    this.service.delete(this.item.alarm_catalog_id).subscribe({
      next: () => this.router.navigate(['/alarm-catalog']),
      error: (err) => {
        this.deleteError = err?.error?.detail || 'Failed to delete the alarm.';
        this.deleting = false;
      }
    });
  }
}
