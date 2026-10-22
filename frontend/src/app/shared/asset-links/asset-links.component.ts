import { CommonModule } from '@angular/common';
import { Component, Input } from '@angular/core';
import { RouterLink } from '@angular/router';

export type LinkedAssetType = 'battery_system' | 'pcs' | 'ems_controller' | 'hvac_unit' | 'battery_module';

interface QuickLink {
  key: 'telemetry' | 'summary' | 'hierarchy';
  label: string;
  title: string;
  route: string;
  queryParams: Record<string, string | number>;
}

/** Where each asset type's telemetry and daily summary live, and the query param they read. */
const TARGETS: Record<LinkedAssetType, { telemetry: string; summary: string; summaryLabel: string; param: string }> = {
  battery_system: {
    telemetry: '/telemetry/bms',
    summary: '/analytics/daily-summary',
    summaryLabel: 'Daily Battery Summary',
    param: 'system'
  },
  pcs: { telemetry: '/telemetry/pcs', summary: '/analytics/daily-pcs-summary', summaryLabel: 'Daily PCS Summary', param: 'pcs' },
  ems_controller: {
    telemetry: '/telemetry/ems',
    summary: '/analytics/daily-ems-summary',
    summaryLabel: 'Daily EMS Summary',
    param: 'ems'
  },
  hvac_unit: {
    telemetry: '/telemetry/hvac',
    summary: '/analytics/daily-hvac-summary',
    summaryLabel: 'Daily HVAC Summary',
    param: 'hvac'
  },
  // the module summary is per pack; ?module= highlights this module in its comparison table
  battery_module: {
    telemetry: '/telemetry/module',
    summary: '/analytics/daily-module-summary',
    summaryLabel: 'Daily Module Summary',
    param: 'module'
  }
};

/**
 * Shortcuts from an asset to its telemetry, daily summary and place in the asset hierarchy.
 * `variant="pills"` for page headers, `variant="icons"` for table rows.
 */
@Component({
  selector: 'app-asset-links',
  standalone: true,
  imports: [CommonModule, RouterLink],
  templateUrl: './asset-links.component.html',
  styleUrl: './asset-links.component.scss'
})
export class AssetLinksComponent {
  @Input({ required: true }) assetType!: LinkedAssetType;
  @Input({ required: true }) assetId!: number;
  @Input() name = '';
  /** The asset's battery system, passed on to summaries that also read ?system= (EMS, HVAC). */
  @Input() systemId: number | null = null;
  /** A module's pack: the Daily Module Summary is scoped to it. */
  @Input() packId: number | null = null;
  @Input() variant: 'pills' | 'icons' = 'pills';

  get links(): QuickLink[] {
    const t = TARGETS[this.assetType];
    const of = this.name ? ` for ${this.name}` : '';
    const params: Record<string, number> = { [t.param]: this.assetId };
    const summaryParams = { ...params };
    if ((this.assetType === 'ems_controller' || this.assetType === 'hvac_unit') && this.systemId) {
      summaryParams['system'] = this.systemId;
    }
    if (this.assetType === 'battery_module' && this.packId) {
      summaryParams['pack'] = this.packId;
    }
    return [
      { key: 'telemetry', label: 'Telemetry', title: `Open telemetry${of}`, route: t.telemetry, queryParams: params },
      { key: 'summary', label: 'Daily Summary', title: `Open the ${t.summaryLabel}${of}`, route: t.summary, queryParams: summaryParams },
      {
        key: 'hierarchy',
        label: 'Hierarchy',
        title: `Show${this.name ? ' ' + this.name : ''} in the asset hierarchy`,
        route: '/asset-hierarchy',
        queryParams: { type: this.assetType, id: this.assetId }
      }
    ];
  }
}
