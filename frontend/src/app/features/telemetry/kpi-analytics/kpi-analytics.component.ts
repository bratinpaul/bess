import { CommonModule } from '@angular/common';
import { Component, Input, OnInit, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { ChartConfiguration } from 'chart.js';

import {
  KpiCalculateResult,
  KpiConfig,
  KpiData,
  KpiDefinition,
  KpiDomain,
  KpiEntity,
  KpiRun
} from '../../../core/models/kpi.model';
import { KpiService } from '../../../core/services/kpi.service';
import { ChartCanvasComponent } from '../graphs/chart-canvas.component';

/** Used only when a KPI has no colour in the config (validated categorical order). */
const FALLBACK_COLORS = ['#2f6fed', '#e8830c', '#12a37f', '#7c5cdb'];
const GRID = '#eceef0';
const TICK = '#6b6f76';

interface SummaryCard {
  code: string;
  name: string;
  unit: string | null;
  value: number | null;
  decimals: number;
  basis: string;
}

interface KpiChartView {
  title: string;
  group: string;
  config: ChartConfiguration;
}

/** One group of the config: its range cards and charts. */
interface GroupSection {
  code: string;
  name: string;
  cards: SummaryCard[];
  charts: KpiChartView[];
}

/** A run of table columns under one group header. */
interface ColumnGroup {
  name: string;
  span: number;
}

type KpiSubTab = 'results' | 'definitions' | 'runs';

/**
 * Analytics tab of a telemetry page (BMS per battery system, PCS per PCS unit): the KPIs defined in the domain's
 * backend/kpi_config/<domain>_kpi.yaml, stored per entity per day in battery_ml.<domain>_kpi. Calculation only runs
 * when the user presses "Calculate KPIs" (no polling).
 */
@Component({
  selector: 'app-kpi-analytics',
  standalone: true,
  imports: [CommonModule, FormsModule, ChartCanvasComponent],
  templateUrl: './kpi-analytics.component.html',
  styleUrl: './kpi-analytics.component.scss'
})
export class KpiAnalyticsComponent implements OnInit {
  private kpiService = inject(KpiService);
  private route = inject(ActivatedRoute);
  private router = inject(Router);

  readonly subTabs: { key: KpiSubTab; label: string }[] = [
    { key: 'results', label: 'KPI results' },
    { key: 'definitions', label: 'KPI definitions' },
    { key: 'runs', label: 'KPI runs' }
  ];
  /** kept in the URL (?kpi=definitions | runs) so it survives a reload */
  subTab: KpiSubTab = 'results';

  @Input({ required: true }) domain!: KpiDomain;
  /** entity id from the page (e.g. ?system=<id> / the PCS filter), if any */
  @Input() initialEntityId: string | number | null = '';

  entities: KpiEntity[] = [];
  config: KpiConfig | null = null;
  configError: string | null = null;

  entityId: number | null = null;
  start = '';
  end = '';
  telemetryRange = '';

  data: KpiData | null = null;
  loading = false;
  error: string | null = null;

  allEntities = false;
  calculating = false;
  calcResult: KpiCalculateResult | null = null;
  calcError: string | null = null;

  runs: KpiRun[] = [];
  runsError: string | null = null;

  /** '' = all groups */
  selectedGroup = '';
  sections: GroupSection[] = [];
  /** rollup row (config `tiles`) */
  tiles: SummaryCard[] = [];
  /** table columns: the stored KPIs of the range in the selected group(s), in config order */
  columns: KpiData['kpis'] = [];
  columnGroups: ColumnGroup[] = [];
  staleDays = 0;

  systemParams: Record<string, number | null> = {};
  showParams = true;

  ngOnInit(): void {
    this.selectedGroup = this.readGroupPref();
    const kpi = this.route.snapshot.queryParamMap.get('kpi');
    if (kpi === 'definitions' || kpi === 'runs') {
      this.subTab = kpi;
    }
    this.loadConfig();
    this.loadRuns();
    this.loadEntities();
  }

  private loadEntities(): void {
    this.kpiService.entities(this.domain).subscribe({
      next: (list) => {
        this.entities = list;
        if (list.length === 0) {
          return;
        }
        const wanted = Number(this.initialEntityId);
        // prefer the page's entity, then the first one that has telemetry
        const match = list.find((e) => e.id === wanted) ?? list.find((e) => e.samples > 0) ?? list[0];
        this.entityId = match.id;
        this.onEntityChange();
      },
      error: () => (this.error = `Could not load the ${this.domain.entityPlural}. Is the backend running?`)
    });
  }

  setSubTab(tab: KpiSubTab): void {
    this.subTab = tab;
    this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { kpi: tab === 'results' ? null : tab },
      queryParamsHandling: 'merge',
      replaceUrl: true
    });
    if (tab === 'results') {
      this.rebuildViews(); // charts are re-created when the results come back into view
    }
  }

  get selectedEntityName(): string {
    return this.entities.find((e) => e.id === this.entityId)?.name ?? '';
  }

  get groups() {
    return this.config?.groups ?? [];
  }

  get paramEntries(): { name: string; value: number }[] {
    return Object.entries(this.config?.params ?? {}).map(([name, value]) => ({ name, value }));
  }

  get systemParamEntries() {
    return Object.entries(this.config?.system_params ?? {}).map(([name, p]) => ({
      name,
      ...p,
      value: this.systemParams[name] ?? null,
      overridden: this.entityId !== null && this.config?.system_overrides?.[String(this.entityId)]?.[name] !== undefined
    }));
  }

  get queryEntries() {
    return Object.entries(this.config?.queries ?? {}).map(([name, q]) => ({ name, ...q }));
  }

  kpisOfGroup(group: string): KpiDefinition[] {
    return this.config?.kpis.filter((k) => k.group === group) ?? [];
  }

  groupName(code: string): string {
    return this.config?.groups.find((g) => g.code === code)?.name ?? code;
  }

  selectGroup(code: string): void {
    this.selectedGroup = code;
    try {
      localStorage.setItem(this.domain.storageKey, code);
    } catch {
      /* the selection just isn't remembered */
    }
    this.rebuildViews();
  }

  private readGroupPref(): string {
    try {
      return localStorage.getItem(this.domain.storageKey) ?? '';
    } catch {
      return '';
    }
  }

  get enabledKpis(): KpiDefinition[] {
    return this.config?.kpis.filter((k) => k.enabled) ?? [];
  }

  loadConfig(): void {
    this.configError = null;
    this.kpiService.config(this.domain).subscribe({
      next: (cfg) => {
        this.config = cfg;
        this.rebuildViews();
      },
      error: (err) => {
        this.config = null;
        this.configError = err?.error?.detail || 'Could not read the KPI configuration. Is the backend running?';
      }
    });
  }

  loadRuns(): void {
    this.runsError = null;
    this.kpiService.runs(this.domain).subscribe({
      next: (runs) => (this.runs = runs),
      error: () => (this.runsError = 'Could not load the calculation history.')
    });
  }

  onEntityChange(): void {
    if (this.entityId === null) {
      return;
    }
    this.data = null;
    this.telemetryRange = '';
    this.systemParams = {};
    this.kpiService.systemParams(this.domain, this.entityId).subscribe({
      next: (p) => (this.systemParams = p),
      error: () => (this.systemParams = {})
    });
    this.kpiService.dateRange(this.domain, this.entityId).subscribe({
      next: (r) => {
        this.telemetryRange = r.telemetry_start ? `${r.telemetry_start} → ${r.telemetry_end}` : 'no telemetry';
        // show what is stored; before the first calculation, offer the telemetry range
        this.start = r.kpi_start ?? r.telemetry_start ?? '';
        this.end = r.kpi_end ?? r.telemetry_end ?? '';
        this.loadData();
      },
      error: () => this.loadData()
    });
  }

  loadData(): void {
    if (this.entityId === null) {
      return;
    }
    if (this.start && this.end && this.start > this.end) {
      this.error = 'From must be on or before To.';
      return;
    }
    this.loading = true;
    this.error = null;
    this.kpiService.list(this.domain, this.entityId, this.start || undefined, this.end || undefined).subscribe({
      next: (data) => {
        this.data = data;
        this.loading = false;
        this.rebuildViews();
      },
      error: (err) => {
        this.loading = false;
        this.data = null;
        this.rebuildViews();
        this.error = err?.error?.detail || 'Could not load KPIs. Is the backend running?';
      }
    });
  }

  calculate(): void {
    if (!this.allEntities && this.entityId === null) {
      return;
    }
    if (this.start && this.end && this.start > this.end) {
      this.calcError = 'From must be on or before To.';
      return;
    }
    this.calculating = true;
    this.calcError = null;
    this.calcResult = null;
    this.kpiService
      .calculate(this.domain, {
        entityId: this.allEntities ? null : this.entityId,
        start_date: this.start || null,
        end_date: this.end || null
      })
      .subscribe({
        next: (result) => {
          this.calculating = false;
          this.calcResult = result;
          this.loadData();
          this.loadRuns();
        },
        error: (err) => {
          this.calculating = false;
          this.calcError = err?.error?.detail || 'KPI calculation failed. Is the backend running?';
          this.loadRuns();
        }
      });
  }

  value(day: KpiData['days'][number], code: string): number | null {
    const v = day.values[code];
    return v === undefined ? null : v;
  }

  decimals(code: string): number {
    return this.config?.kpis.find((k) => k.code === code)?.decimals ?? 2;
  }

  format(v: number | null, decimals: number): string {
    if (v === null || v === undefined || !Number.isFinite(v)) {
      return '—';
    }
    return v.toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
  }

  runScope(run: KpiRun): string {
    const who = run.entity_names?.length ? run.entity_names.join(', ') : `All ${this.domain.entityPlural}`;
    const range = run.start_date || run.end_date ? `${run.start_date ?? '…'} → ${run.end_date ?? '…'}` : 'all days';
    return `${who} · ${range}`;
  }

  // --- views ---------------------------------------------------------------------------------------------------------

  private rebuildViews(): void {
    const days = this.data?.days ?? [];
    const groups = (this.config?.groups ?? []).filter((g) => !this.selectedGroup || g.code === this.selectedGroup);
    if (this.selectedGroup && groups.length === 0) {
      this.selectedGroup = ''; // the remembered group is gone from the config
      this.rebuildViews();
      return;
    }
    const stored = new Set((this.data?.kpis ?? []).map((k) => k.code));
    this.staleDays = days.filter((d) => d.stale).length;

    const defs = new Map((this.config?.kpis ?? []).map((k) => [k.code, k]));
    this.tiles = (this.config?.tiles ?? [])
      .map((code) => defs.get(code))
      .filter((k): k is KpiDefinition => !!k && k.enabled && stored.has(k.code))
      .map((k) => this.summaryCard(k, days));

    const charts = (this.config?.charts ?? [])
      .map((chart) => this.chartConfig(chart.title, chart.type, chart.kpis, days))
      .filter((c): c is KpiChartView => c !== null);

    this.sections = groups.map((g) => ({
      code: g.code,
      name: g.name,
      cards: this.kpisOfGroup(g.code)
        .filter((k) => k.enabled && stored.has(k.code))
        .map((k) => this.summaryCard(k, days)),
      charts: charts.filter((c) => c.group === g.code)
    }));

    // table: stored KPIs in config order, grouped; stored codes no longer in the config go last
    const groupOf = new Map((this.config?.kpis ?? []).map((k) => [k.code, k.group]));
    const all = this.data?.kpis ?? [];
    const ordered = [
      ...groups.flatMap((g) => all.filter((k) => groupOf.get(k.code) === g.code)),
      ...(this.selectedGroup ? [] : all.filter((k) => !groupOf.has(k.code)))
    ];
    this.columns = ordered;
    this.columnGroups = [];
    for (const col of ordered) {
      const name = groupOf.has(col.code) ? this.groupName(groupOf.get(col.code)!) : 'Not in config';
      const last = this.columnGroups[this.columnGroups.length - 1];
      if (last && last.name === name) {
        last.span++;
      } else {
        this.columnGroups.push({ name, span: 1 });
      }
    }
  }

  private summaryCard(k: KpiDefinition, days: KpiData['days']): SummaryCard {
    const n = days.filter((d) => d.values[k.code] !== null && d.values[k.code] !== undefined).length;
    const plural = `${n} day${n === 1 ? '' : 's'}`;
    const basis = {
      sum: `total of ${plural}`,
      avg: `average of ${plural}`,
      min: `lowest of ${plural}`,
      max: `highest of ${plural}`,
      last: `last of ${plural}`,
      formula: `over ${plural} (${k.formula_text})`
    }[k.summary];
    return {
      code: k.code,
      name: k.name,
      unit: k.unit,
      value: this.data?.summary?.[k.code] ?? null,
      decimals: k.decimals,
      basis
    };
  }

  private chartConfig(title: string, type: 'bar' | 'line', codes: string[], days: KpiData['days']): KpiChartView | null {
    const defs = codes
      .map((code) => this.config?.kpis.find((k) => k.code === code))
      .filter((k): k is KpiDefinition => !!k && (this.data?.kpis ?? []).some((c) => c.code === k.code));
    if (defs.length === 0 || days.length === 0) {
      return null;
    }
    const group = defs[0].group;
    const labels = days.map((d) => d.kpi_date);
    const unit = defs[0].unit ?? '';
    const datasets = defs.map((k, i) => {
      const color = k.color ?? FALLBACK_COLORS[i % FALLBACK_COLORS.length];
      const data = days.map((d) => d.values[k.code] ?? null);
      if (type === 'bar') {
        return {
          label: k.name,
          data,
          backgroundColor: color,
          borderRadius: 4,
          borderSkipped: 'start' as const,
          maxBarThickness: 18,
          categoryPercentage: 0.8,
          barPercentage: 0.9
        };
      }
      return {
        label: k.name,
        data,
        borderColor: color,
        backgroundColor: color,
        borderWidth: 2,
        borderDash: k.dashed ? [6, 4] : [],
        pointRadius: days.length > 45 ? 0 : 2.5,
        pointHoverRadius: 5,
        tension: 0.2,
        spanGaps: false,
        // a dashed cross-check series is drawn over its (often identical) main series so it stays visible
        order: k.dashed ? 0 : 1
      };
    });

    const config: ChartConfiguration = {
      type,
      data: { labels, datasets } as ChartConfiguration['data'],
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: {
            display: defs.length > 1,
            position: 'bottom',
            labels: type === 'line' ? { boxWidth: 24, boxHeight: 2, color: TICK } : { boxWidth: 12, boxHeight: 12, color: TICK }
          },
          tooltip: {
            callbacks: {
              label: (ctx) => {
                const def = defs[ctx.datasetIndex];
                const v = ctx.parsed.y;
                return ` ${def.name}: ${this.format(v, def.decimals)} ${def.unit ?? ''}`;
              }
            }
          }
        },
        scales: {
          x: { grid: { display: false }, ticks: { color: TICK, maxRotation: 0, autoSkipPadding: 12 } },
          y: {
            grid: { color: GRID },
            border: { display: false },
            ticks: { color: TICK },
            title: { display: !!unit, text: unit, color: TICK }
          }
        }
      }
    };
    return { title, group, config };
  }
}
