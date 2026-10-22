import { CommonModule } from '@angular/common';
import { Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { forkJoin } from 'rxjs';

import {
  BatchLog,
  BatchLogPage,
  BatchStatusValue,
  GeneratorCalendar,
  GeneratorFieldName,
  GeneratorOptions,
  GeneratorPreview,
  GeneratorStatus,
  GeneratorSystem
} from '../../../core/models/batch.model';
import { BatchService } from '../../../core/services/batch.service';

const PAGE_SIZE = 15;

type Scenario = 'normal' | 'heat' | 'monsoon' | 'maintenance' | 'outage';

interface CalendarDay {
  iso: string;
  day: number;
  inRange: boolean;
}

interface CalendarMonth {
  label: string;
  weeks: (CalendarDay | null)[][];
}

/** One selected site: its preview (master data), the values used for this run and its scenario calendar. */
interface SitePlan {
  preview: GeneratorPreview;
  values: Record<GeneratorFieldName, number | string>;
  calendar: GeneratorCalendar;
  error: string | null;
  reproposing: boolean;
}

/**
 * Batch -> Historical Generator: generate historical telemetry files for one or more sites from the sample files in
 * input/historical (same layout as the Bhadla folder). Steps: 1 sites and date range - 2 mapping and scenarios per
 * site (from master data, editable for this run) - 3 Generate - 4 monitor by hand (Refresh status). Nothing runs or
 * refreshes on its own.
 */
@Component({
  selector: 'app-historical-generator',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  templateUrl: './historical-generator.component.html',
  styleUrls: [
    '../realtime-batch/realtime-batch.component.scss',
    '../historical-load/historical-load.component.scss',
    './historical-generator.component.scss'
  ]
})
export class HistoricalGeneratorComponent implements OnInit {
  options: GeneratorOptions | null = null;
  optionsError: string | null = null;

  // 1 · sites and range
  selected = new Set<number>();
  dateFrom = '';
  dateTo = '';
  moduleFrom = '';

  // 2 · mapping and scenarios
  plans = new Map<number, SitePlan>();
  preparedRange = '';
  preparing = false;
  prepareError: string | null = null;
  activeId: number | null = null;

  // 3 / 4 · run, monitored by hand
  status: GeneratorStatus | null = null;
  starting = false;
  runError: string | null = null;
  refreshing = false;
  refreshedAt: Date | null = null;

  // batch log
  logs: BatchLogPage | null = null;
  logsLoading = true;
  statusFilter: BatchStatusValue | '' = '';
  offset = 0;
  readonly pageSize = PAGE_SIZE;
  expanded: number | null = null;
  readonly statuses: BatchStatusValue[] = ['SUCCESS', 'PARTIAL', 'FAILED'];
  readonly weekdays = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  readonly legend: { key: Scenario; label: string }[] = [
    { key: 'normal', label: 'Sample mix' },
    { key: 'heat', label: 'Heat wave' },
    { key: 'monsoon', label: 'Monsoon / low price' },
    { key: 'maintenance', label: 'Planned maintenance' },
    { key: 'outage', label: 'Forced outage' }
  ];

  constructor(private service: BatchService) {}

  ngOnInit(): void {
    this.service.generatorOptions().subscribe({
      next: (options) => {
        this.options = options;
        this.dateFrom = options.default_from;
        this.dateTo = options.default_to;
        this.moduleFrom = this.defaultModuleFrom();
      },
      error: (err) => (this.optionsError = err?.error?.detail || 'Could not load the sites. Is the backend running?')
    });
    this.refresh();
  }

  // ---------------------------------------------------------------- 1 · sites and range

  isSelected(id: number): boolean {
    return this.selected.has(id);
  }

  toggleSite(system: GeneratorSystem): void {
    if (!system.ready || this.running) {
      return;
    }
    const id = system.battery_system_id;
    if (this.selected.has(id)) {
      this.selected.delete(id);
      this.plans.delete(id);
      if (this.activeId === id) {
        this.activeId = this.planIds[0] ?? null;
      }
    } else {
      this.selected.add(id);
    }
    this.selected = new Set(this.selected);
  }

  get days(): number {
    if (!this.dateFrom || !this.dateTo) {
      return 0;
    }
    return Math.round((Date.parse(this.dateTo) - Date.parse(this.dateFrom)) / 86400000) + 1;
  }

  get rangeError(): string | null {
    if (!this.dateFrom || !this.dateTo) {
      return 'Choose the start and end dates';
    }
    if (this.days < 1) {
      return 'The end date is before the start date';
    }
    if (this.options && this.days > this.options.max_days) {
      return `At most ${this.options.max_days} days at once (${this.days} chosen)`;
    }
    if (this.moduleFrom && (this.moduleFrom < this.dateFrom || this.moduleFrom > this.dateTo)) {
      return 'Module data must start inside the date range';
    }
    return null;
  }

  defaultModuleFrom(): string {
    if (!this.dateFrom || !this.dateTo) {
      return '';
    }
    const from = addDays(this.dateTo, -29);
    return from < this.dateFrom ? this.dateFrom : from;
  }

  onRangeChange(): void {
    this.moduleFrom = this.defaultModuleFrom();
  }

  get moduleDays(): number {
    return this.moduleFrom && this.dateTo ? Math.round((Date.parse(this.dateTo) - Date.parse(this.moduleFrom)) / 86400000) + 1 : 0;
  }

  get rangeKey(): string {
    return `${this.dateFrom}|${this.dateTo}`;
  }

  /** The prepared mapping / calendars no longer match the range or the selection. */
  get needsPrepare(): boolean {
    return (
      this.selected.size > 0 &&
      (this.preparedRange !== this.rangeKey || Array.from(this.selected).some((id) => !this.plans.has(id)))
    );
  }

  // ---------------------------------------------------------------- 2 · mapping and scenarios

  /** Read each selected site's master data and proposed scenarios (sites already prepared keep their edits,
   *  unless the range changed: then their scenarios are proposed again for the new range). */
  prepare(): void {
    if (this.rangeError || !this.selected.size) {
      return;
    }
    const rangeChanged = this.preparedRange !== this.rangeKey;
    const ids = Array.from(this.selected).filter((id) => rangeChanged || !this.plans.has(id));
    if (!ids.length) {
      return;
    }
    this.preparing = true;
    this.prepareError = null;
    forkJoin(
      ids.map((id) =>
        this.service.generatorPreview({
          battery_system_id: id,
          date_from: this.dateFrom,
          date_to: this.dateTo,
          overrides: this.overrides(this.plans.get(id))
        })
      )
    ).subscribe({
      next: (previews) => {
        previews.forEach((p) => {
          const old = this.plans.get(p.battery_system_id);
          const values = old ? old.values : masterValues(p); // mapping edits survive a range change; scenarios are re-proposed
          this.plans.set(p.battery_system_id, { preview: p, values: { ...values }, calendar: clone(p.calendar), error: null, reproposing: false });
        });
        this.plans = new Map(this.plans);
        this.preparedRange = this.rangeKey;
        this.activeId = this.activeId && this.plans.has(this.activeId) ? this.activeId : this.planIds[0] ?? null;
        this.preparing = false;
      },
      error: (err) => {
        this.prepareError = err?.error?.detail || 'Could not read the master data.';
        this.preparing = false;
      }
    });
  }

  get planIds(): number[] {
    return (this.options?.systems ?? []).map((s) => s.battery_system_id).filter((id) => this.plans.has(id) && this.selected.has(id));
  }

  get active(): SitePlan | undefined {
    return this.activeId !== null ? this.plans.get(this.activeId) : undefined;
  }

  systemOf(id: number): GeneratorSystem | undefined {
    return this.options?.systems.find((s) => s.battery_system_id === id);
  }

  /** The fields that differ from master data (sent as overrides). */
  overrides(plan: SitePlan | undefined): Record<string, number | string> {
    const out: Record<string, number | string> = {};
    if (!plan) {
      return out;
    }
    for (const f of plan.preview.fields) {
      const v = plan.values[f.name];
      if (v !== null && v !== undefined && v !== '' && String(v) !== String(f.master)) {
        out[f.name] = f.kind === 'str' ? String(v) : Number(v);
      }
    }
    return out;
  }

  changedCount(plan: SitePlan): number {
    return Object.keys(this.overrides(plan)).length;
  }

  isChanged(plan: SitePlan, name: GeneratorFieldName, master: number | string): boolean {
    const v = plan.values[name];
    return v !== null && v !== undefined && v !== '' && String(v) !== String(master);
  }

  resetField(plan: SitePlan, name: GeneratorFieldName, master: number | string): void {
    plan.values[name] = master;
  }

  resetMapping(plan: SitePlan): void {
    plan.values = masterValues(plan.preview);
  }

  climateLabel(plan: SitePlan): string {
    return plan.preview.choices.climate_key.find((c) => c.key === plan.values.climate_key)?.label ?? '';
  }

  heatAmp(plan: SitePlan): [number, number] {
    return plan.preview.choices.climate_key.find((c) => c.key === plan.values.climate_key)?.heat_amp ?? plan.preview.heat_amp;
  }

  scaling(plan: SitePlan): { power: number; soc: number } {
    const kw = Number(plan.values.rated_kw) || 0;
    const kwh = Number(plan.values.capacity_kwh) || 1;
    return { power: kw / 1000, soc: ((kw / 1000) * 2000) / kwh };
  }

  /** Ask the backend for a new scenario proposal using this site's current values (e.g. after a climate change). */
  repropose(plan: SitePlan): void {
    plan.reproposing = true;
    plan.error = null;
    this.service
      .generatorPreview({
        battery_system_id: plan.preview.battery_system_id,
        date_from: this.dateFrom,
        date_to: this.dateTo,
        overrides: this.overrides(plan)
      })
      .subscribe({
        next: (p) => {
          plan.calendar = clone(p.calendar);
          plan.reproposing = false;
        },
        error: (err) => {
          plan.error = err?.error?.detail || 'Could not propose scenarios.';
          plan.reproposing = false;
        }
      });
  }

  resetCalendar(plan: SitePlan): void {
    plan.calendar = clone(plan.preview.calendar);
  }

  clearCalendar(plan: SitePlan): void {
    plan.calendar = { heat: {}, monsoon: [], low_insulation: null, maintenance: null, outage: null };
  }

  // calendar grid

  get months(): CalendarMonth[] {
    if (!this.dateFrom || !this.dateTo || this.rangeError) {
      return [];
    }
    const out: CalendarMonth[] = [];
    let cursor = this.dateFrom.slice(0, 7) + '-01';
    while (cursor <= this.dateTo) {
      const [y, m] = cursor.split('-').map(Number);
      const first = new Date(Date.UTC(y, m - 1, 1));
      const length = new Date(Date.UTC(y, m, 0)).getUTCDate();
      const lead = (first.getUTCDay() + 6) % 7;
      const cells: (CalendarDay | null)[] = Array(lead).fill(null);
      for (let d = 1; d <= length; d++) {
        const iso = `${cursor.slice(0, 8)}${String(d).padStart(2, '0')}`;
        cells.push({ iso, day: d, inRange: iso >= this.dateFrom && iso <= this.dateTo });
      }
      while (cells.length % 7) {
        cells.push(null);
      }
      const weeks: (CalendarDay | null)[][] = [];
      for (let i = 0; i < cells.length; i += 7) {
        weeks.push(cells.slice(i, i + 7));
      }
      out.push({ label: first.toLocaleDateString('en-GB', { month: 'long', year: 'numeric', timeZone: 'UTC' }), weeks });
      cursor = m === 12 ? `${y + 1}-01-01` : `${y}-${String(m + 1).padStart(2, '0')}-01`;
    }
    return out;
  }

  scenarioOf(cal: GeneratorCalendar, iso: string): Scenario {
    if (cal.maintenance?.date === iso) {
      return 'maintenance';
    }
    if (cal.outage?.date === iso) {
      return 'outage';
    }
    if (iso in cal.heat) {
      return 'heat';
    }
    return cal.monsoon.includes(iso) ? 'monsoon' : 'normal';
  }

  /** Click a day: sample mix -> heat wave -> monsoon -> sample mix (maintenance / outage days are set below). */
  cycleDay(plan: SitePlan, day: CalendarDay): void {
    if (!day.inRange || this.running) {
      return;
    }
    const cal = plan.calendar;
    const now = this.scenarioOf(cal, day.iso);
    if (now === 'maintenance' || now === 'outage') {
      return;
    }
    if (now === 'normal') {
      const [lo, hi] = this.heatAmp(plan);
      cal.heat = { ...cal.heat, [day.iso]: Math.round(((lo + hi) / 2) * 10) / 10 };
    } else if (now === 'heat') {
      const { [day.iso]: _, ...rest } = cal.heat;
      cal.heat = rest;
      cal.monsoon = [...cal.monsoon, day.iso].sort();
    } else {
      cal.monsoon = cal.monsoon.filter((d) => d !== day.iso);
      if (cal.low_insulation === day.iso) {
        cal.low_insulation = null;
      }
    }
  }

  dayTitle(plan: SitePlan, day: CalendarDay): string {
    const s = this.scenarioOf(plan.calendar, day.iso);
    const cal = plan.calendar;
    const text: Record<Scenario, string> = {
      normal: 'Sample mix',
      heat: `Heat wave: afternoon +${cal.heat[day.iso]} °C, power derated to 80 %`,
      monsoon: `Monsoon / low price: cool, humid, shallow cycling${cal.low_insulation === day.iso ? '; DC insulation dip' : ''}`,
      maintenance: `Planned maintenance ${cal.maintenance?.start}–${cal.maintenance?.end}`,
      outage: `Forced outage (PCS ground fault), restart ${cal.outage?.restart}`
    };
    const hint = s === 'maintenance' || s === 'outage' ? ' · change it below' : ' · click to change';
    return `${day.iso} · ${text[s]}${hint}`;
  }

  heatDays(cal: GeneratorCalendar): string[] {
    return Object.keys(cal.heat).sort();
  }

  setHeat(cal: GeneratorCalendar, iso: string, value: number): void {
    cal.heat = { ...cal.heat, [iso]: Number(value) };
  }

  /** Days free for maintenance / an outage (not used by another scenario). */
  freeDays(cal: GeneratorCalendar, keep?: string | null): string[] {
    const out: string[] = [];
    for (let i = 0; i < this.days; i++) {
      const iso = addDays(this.dateFrom, i);
      const s = this.scenarioOf(cal, iso);
      if (s === 'normal' || iso === keep) {
        out.push(iso);
      }
    }
    return out;
  }

  toggleMaintenance(cal: GeneratorCalendar, on: boolean): void {
    const free = this.freeDays(cal);
    cal.maintenance = on && free.length ? { date: free[Math.floor(free.length / 3)], start: '07:00', end: '17:00' } : null;
  }

  toggleOutage(cal: GeneratorCalendar, on: boolean): void {
    const free = this.freeDays(cal);
    cal.outage = on && free.length ? { date: free[Math.floor((free.length * 2) / 3)], restart: '16:30' } : null;
  }

  counts(cal: GeneratorCalendar): Record<Scenario, number> {
    return {
      normal: this.days - Object.keys(cal.heat).length - cal.monsoon.length - (cal.maintenance ? 1 : 0) - (cal.outage ? 1 : 0),
      heat: Object.keys(cal.heat).length,
      monsoon: cal.monsoon.length,
      maintenance: cal.maintenance ? 1 : 0,
      outage: cal.outage ? 1 : 0
    };
  }

  /** Problems the backend would refuse (shown before Generate). */
  calendarProblems(cal: GeneratorCalendar): string[] {
    const out: string[] = [];
    if (cal.maintenance && cal.maintenance.end <= cal.maintenance.start) {
      out.push('Maintenance must end after it starts');
    }
    if (cal.outage && (cal.outage.restart < '13:30' || cal.outage.restart > '17:00')) {
      out.push('The outage restart must be between 13:30 and 17:00');
    }
    for (const t of [cal.maintenance?.start, cal.maintenance?.end, cal.outage?.restart]) {
      if (t && Number(t.slice(3, 5)) % 5) {
        out.push(`${t}: use 5-minute times`);
      }
    }
    return out;
  }

  // ---------------------------------------------------------------- 3 · generate

  get canGenerate(): boolean {
    return (
      !!this.planIds.length &&
      !this.needsPrepare &&
      !this.rangeError &&
      !this.running &&
      !this.starting &&
      this.planIds.every((id) => !this.calendarProblems(this.plans.get(id)!.calendar).length)
    );
  }

  get replacing(): { site: string; files: number }[] {
    return this.planIds
      .map((id) => this.plans.get(id)!.preview)
      .filter((p) => p.existing_files > 0)
      .map((p) => ({ site: p.folder_relative, files: p.existing_files }));
  }

  generate(): void {
    if (!this.canGenerate) {
      return;
    }
    this.starting = true;
    this.runError = null;
    this.service
      .generatorRun({
        date_from: this.dateFrom,
        date_to: this.dateTo,
        module_from: this.moduleFrom || null,
        sites: this.planIds.map((id) => {
          const plan = this.plans.get(id)!;
          return {
            battery_system_id: id,
            site_name: plan.preview.site_name,
            overrides: this.overrides(plan),
            calendar: plan.calendar
          };
        })
      })
      .subscribe({
        next: (status) => {
          this.status = status;
          this.refreshedAt = new Date();
          this.starting = false;
        },
        error: (err) => {
          this.runError = err?.error?.detail || 'The generation could not be started.';
          this.starting = false;
        }
      });
  }

  get running(): boolean {
    return !!this.status?.running || this.status?.progress?.status === 'RUNNING';
  }

  /** Manual monitoring: read the current state of the generation and the batch log (nothing refreshes on its own). */
  refresh(): void {
    this.refreshing = true;
    this.service.generatorStatus().subscribe({
      next: (status) => {
        const wasRunning = this.running;
        this.status = status;
        this.refreshedAt = new Date();
        this.refreshing = false;
        if (!this.running && status.progress?.batch_id) {
          this.expanded = status.progress.batch_id;
        }
        if (wasRunning && !this.running) {
          this.reloadOptions(); // folders now hold files
        }
      },
      error: () => (this.refreshing = false)
    });
    this.offset = 0;
    this.loadLogs();
  }

  reloadOptions(): void {
    this.service.generatorOptions().subscribe({ next: (options) => (this.options = options) });
  }

  get siteProgress() {
    return this.status?.progress?.sites ?? [];
  }

  get doneSites(): number {
    return this.siteProgress.filter((s) => s.status === 'DONE' || s.status === 'FAILED').length;
  }

  get percent(): number {
    return this.siteProgress.length ? Math.round((this.doneSites / this.siteProgress.length) * 100) : 0;
  }

  scenarioText(s: Record<string, number> | null): string {
    if (!s) {
      return '';
    }
    return Object.entries(s)
      .filter(([k]) => k !== 'normal')
      .map(([k, n]) => `${n} ${k}`)
      .join(' · ');
  }

  overrideText(o: Record<string, { master: unknown; used: unknown }> | null): string {
    return o ? Object.entries(o).map(([k, v]) => `${k} ${v.master} → ${v.used}`).join(' · ') : '';
  }

  // ---------------------------------------------------------------- batch log

  loadLogs(): void {
    this.logsLoading = true;
    this.service.generatorLogs({ status: this.statusFilter, limit: this.pageSize, offset: this.offset }).subscribe({
      next: (page) => {
        this.logs = page;
        this.logsLoading = false;
      },
      error: () => (this.logsLoading = false)
    });
  }

  setStatusFilter(status: BatchStatusValue | ''): void {
    this.statusFilter = status;
    this.offset = 0;
    this.loadLogs();
  }

  get allCount(): number {
    const c = this.logs?.counts;
    return c ? c.SUCCESS + c.PARTIAL + c.FAILED : 0;
  }

  page(delta: number): void {
    const next = this.offset + delta * this.pageSize;
    if (next >= 0 && next < (this.logs?.total ?? 0)) {
      this.offset = next;
      this.loadLogs();
    }
  }

  toggle(log: BatchLog): void {
    this.expanded = this.expanded === log.batch_id ? null : log.batch_id;
  }

  // ---------------------------------------------------------------- display

  plantTime(iso: string | null | undefined): string {
    return iso ? iso.slice(0, 19).replace('T', ' ') : '—';
  }

  duration(ms: number): string {
    const s = Math.round(ms / 1000);
    return s < 60 ? `${s} s` : `${Math.floor(s / 60)} min ${s % 60} s`;
  }
}

function masterValues(p: GeneratorPreview): Record<GeneratorFieldName, number | string> {
  return Object.fromEntries(p.fields.map((f) => [f.name, f.master])) as Record<GeneratorFieldName, number | string>;
}

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value));
}

function addDays(iso: string, n: number): string {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}
