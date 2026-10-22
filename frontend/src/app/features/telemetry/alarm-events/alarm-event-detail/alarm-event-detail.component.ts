import { CommonModule } from '@angular/common';
import { Component, OnInit } from '@angular/core';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';

import { ASSET_RECORD_ROUTES, AssetType } from '../../../../core/models/asset-hierarchy.model';
import { AlarmEvent, LINKED_ASSET_LABELS, plantTime } from '../../../../core/models/alarm-event.model';
import { AlarmEventService } from '../../../../core/services/alarm-event.service';

@Component({
  selector: 'app-alarm-event-detail',
  standalone: true,
  imports: [CommonModule, RouterLink],
  templateUrl: './alarm-event-detail.component.html',
  styleUrl: './alarm-event-detail.component.scss'
})
export class AlarmEventDetailComponent implements OnInit {
  item: AlarmEvent | null = null;
  loading = true;
  error: string | null = null;
  plantTime = plantTime;
  assetLabels = LINKED_ASSET_LABELS;

  confirmDelete = false;
  deleting = false;
  deleteError: string | null = null;

  constructor(
    private route: ActivatedRoute,
    private router: Router,
    private service: AlarmEventService
  ) {}

  ngOnInit(): void {
    const id = this.route.snapshot.paramMap.get('alarmId') ?? '';
    this.service.get(id).subscribe({
      next: (item) => {
        this.item = item;
        this.loading = false;
      },
      error: () => {
        this.error = `Alarm ${id} not found.`;
        this.loading = false;
      }
    });
  }

  /** Master-data page of the linked asset. */
  get assetLink(): (string | number)[] | null {
    const i = this.item;
    return i?.linked_asset_type && i.linked_asset_id !== null
      ? [ASSET_RECORD_ROUTES[i.linked_asset_type as AssetType], i.linked_asset_id]
      : null;
  }

  /** Minutes from the start to the acknowledgement. */
  get minutesToAck(): number | null {
    const i = this.item;
    if (!i?.acknowledged_at) {
      return null;
    }
    return Math.round((Date.parse(i.acknowledged_at) - Date.parse(i.start_time)) / 60000);
  }

  deleteConfirmed(): void {
    if (!this.item) {
      return;
    }
    this.deleting = true;
    this.service.delete(this.item.alarm_id).subscribe({
      next: () => this.router.navigate(['/telemetry/alarms']),
      error: (err) => {
        this.deleteError = err?.error?.detail || 'Failed to delete the alarm.';
        this.deleting = false;
      }
    });
  }
}
