import { CommonModule } from '@angular/common';
import { Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';

import {
  DAY_TYPE_LABELS,
  DayType,
  PRICE_LEVEL_LABELS,
  PriceLevel,
  TariffEmsOption,
  TariffPeriod
} from '../../../core/models/tariff-period.model';
import { TariffPeriodService } from '../../../core/services/tariff-period.service';

/** A run of hours on the 24 h timeline: a band, or a gap no band covers. */
interface Segment {
  start: number;
  end: number;
  band: TariffPeriod | null;
}

/* Price levels are ordinal, so one hue light -> dark (sequential), cheapest lightest. */
export const LEVEL_COLORS: Record<PriceLevel, { bg: string; ink: string }> = {
  SUPER_OFF_PEAK: { bg: '#fdf0e8', ink: '#7a3a14' },
  OFF_PEAK: { bg: '#f9d3bd', ink: '#7a3a14' },
  SHOULDER: { bg: '#f2a77f', ink: '#4a1f08' },
  SHOULDER_HIGH: { bg: '#e57a46', ink: '#ffffff' },
  PEAK: { bg: '#b8501c', ink: '#ffffff' }
};

const LEVEL_ORDER: PriceLevel[] = ['SUPER_OFF_PEAK', 'OFF_PEAK', 'SHOULDER', 'SHOULDER_HIGH', 'PEAK'];

@Component({
  selector: 'app-tariff-period-list',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  templateUrl: './tariff-period-list.component.html',
  styleUrl: './tariff-period-list.component.scss'
})
export class TariffPeriodListComponent implements OnInit {
  readonly levelLabels = PRICE_LEVEL_LABELS;
  readonly dayLabels = DAY_TYPE_LABELS;
  readonly levelColors = LEVEL_COLORS;
  readonly levels = LEVEL_ORDER;
  readonly hours = Array.from({ length: 25 }, (_, i) => i);

  items: TariffPeriod[] = [];
  ems: TariffEmsOption[] = [];
  seasons: string[] = ['ALL'];
  loading = true;
  error: string | null = null;

  /** null = the shared bands (every EMS without its own) */
  scope: number | null = null;
  season = 'ALL';
  searchTerm = '';

  itemToDelete: TariffPeriod | null = null;
  deleting = false;
  deleteError: string | null = null;

  constructor(private service: TariffPeriodService, private router: Router) {}

  ngOnInit(): void {
    this.service.lookups().subscribe({
      next: (l) => {
        this.ems = l.ems;
        this.seasons = l.seasons;
      },
      error: () => {
        /* EMS names are optional */
      }
    });
    this.fetchData();
  }

  fetchData(): void {
    this.loading = true;
    this.error = null;
    this.service.list().subscribe({
      next: (items) => {
        this.items = items;
        this.loading = false;
      },
      error: () => {
        this.error = 'Could not load the tariff bands. Is the backend running?';
        this.loading = false;
      }
    });
  }

  // ---------------------------------------------------------------- scopes

  /** The shared scope plus every EMS that has bands of its own. */
  get scopes(): { id: number | null; label: string; count: number }[] {
    const own = Array.from(new Set(this.items.filter((i) => i.ems_id !== null).map((i) => i.ems_id as number)));
    return [
      { id: null, label: 'Shared (all EMS)', count: this.items.filter((i) => i.ems_id === null).length },
      ...own.map((id) => ({ id, label: this.emsLabel(id), count: this.items.filter((i) => i.ems_id === id).length }))
    ];
  }

  emsLabel(id: number | null): string {
    if (id === null) {
      return 'Shared (all EMS)';
    }
    const e = this.ems.find((x) => x.ems_id === id);
    return e ? `${e.site_name ?? e.ems_code} · ${e.ems_code}` : `EMS ${id}`;
  }

  /** EMS that use the shared bands (no bands of their own). */
  get sharedUsers(): string {
    const own = new Set(this.items.filter((i) => i.ems_id !== null).map((i) => i.ems_id));
    return this.ems
      .filter((e) => !own.has(e.ems_id))
      .map((e) => e.site_name?.replace(/ BESS Site| Grid Storage Site| Site/, '') ?? e.ems_code)
      .join(', ');
  }

  setScope(id: number | null): void {
    this.scope = id;
  }

  // ---------------------------------------------------------------- timeline

  /** Bands of the scope that apply today on that day type in the chosen season. */
  private applying(day: 'WEEKDAY' | 'WEEKEND'): TariffPeriod[] {
    const today = new Date().toISOString().slice(0, 10);
    return this.items.filter(
      (b) =>
        b.ems_id === this.scope &&
        (b.day_type === 'ALL' || b.day_type === day) &&
        (b.season === 'ALL' || this.season === 'ALL' || b.season === this.season) &&
        (!b.valid_from || b.valid_from <= today) &&
        (!b.valid_to || b.valid_to >= today)
    );
  }

  segments(day: 'WEEKDAY' | 'WEEKEND'): Segment[] {
    const bands = this.applying(day);
    const out: Segment[] = [];
    let h = 0;
    while (h < 24) {
      const band = bands.find((b) => b.start_hour <= h && h < b.end_hour) ?? null;
      const end = band ? band.end_hour : Math.min(24, ...bands.filter((b) => b.start_hour > h).map((b) => b.start_hour), 24);
      out.push({ start: h, end, band });
      h = end;
    }
    return out;
  }

  gapHours(day: 'WEEKDAY' | 'WEEKEND'): number {
    return this.segments(day)
      .filter((s) => !s.band)
      .reduce((n, s) => n + s.end - s.start, 0);
  }

  // ---------------------------------------------------------------- table

  get rows(): TariffPeriod[] {
    const term = this.searchTerm.trim().toLowerCase();
    return this.items
      .filter((b) => b.ems_id === this.scope)
      .filter(
        (b) =>
          !term ||
          [b.band_code, b.band_name, b.price_level, b.day_type, b.season, b.note]
            .filter((v): v is string => !!v)
            .some((v) => v.toLowerCase().includes(term))
      )
      .sort((a, b) => a.day_type.localeCompare(b.day_type) || a.season.localeCompare(b.season) || a.start_hour - b.start_hour);
  }

  hourLabel(h: number): string {
    return `${String(h).padStart(2, '0')}:00`;
  }

  dayLabel(d: DayType): string {
    return this.dayLabels[d] ?? d;
  }

  validity(b: TariffPeriod): string {
    if (!b.valid_from && !b.valid_to) {
      return 'Always';
    }
    return `${b.valid_from ?? '…'} → ${b.valid_to ?? '…'}`;
  }

  price(b: TariffPeriod): string {
    return b.reference_price_mwh === null || b.reference_price_mwh === undefined ? '—' : Number(b.reference_price_mwh).toFixed(1);
  }

  edit(b: TariffPeriod, event?: Event): void {
    event?.stopPropagation();
    this.router.navigate(['/tariff-bands', b.tariff_period_id, 'edit']);
  }

  addLink(): (string | number)[] {
    return ['/tariff-bands/new'];
  }

  addParams(): Record<string, number> {
    return this.scope === null ? {} : { ems: this.scope };
  }

  confirmDelete(b: TariffPeriod, event: Event): void {
    event.stopPropagation();
    this.deleteError = null;
    this.itemToDelete = b;
  }

  cancelDelete(): void {
    this.itemToDelete = null;
  }

  deleteConfirmed(): void {
    const target = this.itemToDelete;
    if (!target) {
      return;
    }
    this.deleting = true;
    this.service.delete(target.tariff_period_id).subscribe({
      next: () => {
        this.items = this.items.filter((i) => i.tariff_period_id !== target.tariff_period_id);
        if (this.scope !== null && !this.items.some((i) => i.ems_id === this.scope)) {
          this.scope = null;
        }
        this.itemToDelete = null;
        this.deleting = false;
      },
      error: (err) => {
        this.deleteError = err?.error?.detail || 'Failed to delete the band.';
        this.deleting = false;
      }
    });
  }
}
