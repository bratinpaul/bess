import { CommonModule } from '@angular/common';
import { Component, OnInit } from '@angular/core';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';

import { DispatchEvent, modeLabel, plantTime } from '../../../../core/models/dispatch-event.model';
import { DispatchEventService } from '../../../../core/services/dispatch-event.service';

@Component({
  selector: 'app-dispatch-event-detail',
  standalone: true,
  imports: [CommonModule, RouterLink],
  templateUrl: './dispatch-event-detail.component.html',
  styleUrl: './dispatch-event-detail.component.scss'
})
export class DispatchEventDetailComponent implements OnInit {
  item: DispatchEvent | null = null;
  loading = true;
  error: string | null = null;
  plantTime = plantTime;
  modeLabel = modeLabel;

  confirmDelete = false;
  deleting = false;
  deleteError: string | null = null;

  constructor(
    private route: ActivatedRoute,
    private router: Router,
    private service: DispatchEventService
  ) {}

  ngOnInit(): void {
    const id = this.route.snapshot.paramMap.get('dispatchId') ?? '';
    this.service.get(id).subscribe({
      next: (item) => {
        this.item = item;
        this.loading = false;
      },
      error: () => {
        this.error = `Dispatch ${id} not found.`;
        this.loading = false;
      }
    });
  }

  num(value: string | number | null | undefined): number | null {
    return value === null || value === undefined || value === '' ? null : Number(value);
  }

  get direction(): 'charge' | 'discharge' | 'none' {
    const p = Number(this.item?.p_setpoint_kw ?? 0);
    return p > 0 ? 'charge' : p < 0 ? 'discharge' : 'none';
  }

  /** Setpoint magnitude in kW (the direction is shown in words). */
  get setpointKw(): number {
    return Math.abs(Number(this.item?.p_setpoint_kw ?? 0));
  }

  /** Minutes between issuing the command and it taking effect. */
  get leadMinutes(): number {
    const i = this.item;
    return i ? Math.round((Date.parse(i.effective_from) - Date.parse(i.issued_at)) / 60000) : 0;
  }

  get socChange(): number | null {
    const a = this.num(this.item?.soc_start_pct);
    const b = this.num(this.item?.soc_end_pct);
    return a === null || b === null ? null : Math.round((b - a) * 10) / 10;
  }

  formatDuration(minutes: number | null): string {
    if (minutes === null) {
      return '';
    }
    if (minutes < 60) {
      return `${Math.round(minutes)} min`;
    }
    const h = Math.floor(minutes / 60);
    const m = Math.round(minutes % 60);
    return m ? `${h} h ${m} min` : `${h} h`;
  }

  deleteConfirmed(): void {
    if (!this.item) {
      return;
    }
    this.deleting = true;
    this.service.delete(this.item.dispatch_id).subscribe({
      next: () => this.router.navigate(['/telemetry/dispatch']),
      error: (err) => {
        this.deleteError = err?.error?.detail || 'Failed to delete the dispatch.';
        this.deleting = false;
      }
    });
  }
}
