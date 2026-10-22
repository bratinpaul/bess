import { Injectable } from '@angular/core';
import { Observable, catchError, forkJoin, map, of, shareReplay } from 'rxjs';

import { BatterySystemService } from './battery-system.service';
import { EmsControllerService } from './ems-controller.service';
import { HvacUnitService } from './hvac-unit.service';
import { PcsService } from './pcs.service';
import { SiteService } from './site.service';

/** The plant (site) and battery system an asset belongs to. */
export interface PlantContext {
  plant: string | null;
  system: string | null;
}

interface Lookups {
  sites: Map<number, string>;
  systems: Map<number, { name: string; siteId: number }>;
  pcs: Map<number, number>;
  ems: Map<number, number>;
  hvac: Map<number, number>;
}

/**
 * Resolves an asset to its plant and battery system from master data (for report headers). The master lists are
 * loaded once and shared; a list that fails to load just leaves the names empty.
 */
@Injectable({ providedIn: 'root' })
export class PlantContextService {
  private lookups$?: Observable<Lookups>;

  constructor(
    private sites: SiteService,
    private systems: BatterySystemService,
    private pcs: PcsService,
    private ems: EmsControllerService,
    private hvac: HvacUnitService
  ) {}

  private load(): Observable<Lookups> {
    const safe = <T>(o: Observable<T[]>) => o.pipe(catchError(() => of([] as T[])));
    this.lookups$ ??= forkJoin({
      sites: safe(this.sites.list()),
      systems: safe(this.systems.list()),
      pcs: safe(this.pcs.list()),
      ems: safe(this.ems.list()),
      hvac: safe(this.hvac.list())
    }).pipe(
      map((r) => ({
        sites: new Map(r.sites.map((s) => [s.site_id, s.site_name])),
        systems: new Map(r.systems.map((s) => [s.battery_system_id, { name: s.system_name, siteId: s.site_id }])),
        pcs: new Map(r.pcs.map((p) => [p.pcs_id, p.system_id])),
        ems: new Map(r.ems.filter((e) => e.battery_system_id !== null).map((e) => [e.ems_id, e.battery_system_id as number])),
        hvac: new Map(r.hvac.filter((h) => h.battery_system_id !== null).map((h) => [h.hvac_id, h.battery_system_id as number]))
      })),
      shareReplay(1)
    );
    return this.lookups$;
  }

  private bySystem(l: Lookups, systemId: number | null | undefined): PlantContext {
    const system = systemId === null || systemId === undefined ? undefined : l.systems.get(systemId);
    return { plant: system ? l.sites.get(system.siteId) ?? null : null, system: system?.name ?? null };
  }

  forSystem(systemId: number | null | undefined): Observable<PlantContext> {
    return this.load().pipe(map((l) => this.bySystem(l, systemId)));
  }

  forPcs(pcsId: number): Observable<PlantContext> {
    return this.load().pipe(map((l) => this.bySystem(l, l.pcs.get(pcsId))));
  }

  forEms(emsId: number): Observable<PlantContext> {
    return this.load().pipe(map((l) => this.bySystem(l, l.ems.get(emsId))));
  }

  forHvac(hvacId: number): Observable<PlantContext> {
    return this.load().pipe(map((l) => this.bySystem(l, l.hvac.get(hvacId))));
  }
}
