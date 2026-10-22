import { CommonModule } from '@angular/common';
import { Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';

import {
  ASSET_RECORD_ROUTES,
  ASSET_TYPE_LABELS,
  ASSET_TYPES,
  AssetNodeDetail,
  AssetTreeNode,
  AssetType
} from '../../core/models/asset-hierarchy.model';
import { AssetHierarchyService } from '../../core/services/asset-hierarchy.service';

const PLURALS: Record<AssetType, string> = {
  tenant: 'Tenants',
  site: 'Sites',
  battery_system: 'Battery Systems',
  battery_container: 'Containers',
  battery_pack: 'Packs',
  battery_module: 'Modules',
  pcs: 'PCS',
  ems_controller: 'EMS',
  hvac_unit: 'HVAC'
};

const emptyCounts = () => Object.fromEntries(ASSET_TYPES.map((t) => [t, 0])) as Record<AssetType, number>;

// tree keys are the record (type + source id), which stays stable when a node is removed and re-added
const key = (n: { asset_type: string; source_id: number }) => `${n.asset_type}:${n.source_id}`;

@Component({
  selector: 'app-asset-hierarchy',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  templateUrl: './asset-hierarchy.component.html',
  styleUrl: './asset-hierarchy.component.scss'
})
export class AssetHierarchyComponent implements OnInit {
  roots: AssetTreeNode[] = [];
  visibleRoots: AssetTreeNode[] = [];
  loading = true;
  error: string | null = null;

  searchTerm = '';
  /** Collapsed node keys; everything starts expanded. */
  collapsed = new Set<string>();
  counts = emptyCounts();
  /** Packs start collapsed so the tree is not one long list of modules. */
  private firstLoad = true;

  selectedKey: string | null = null;
  detail: AssetNodeDetail | null = null;
  detailLoading = false;

  syncing = false;
  message: string | null = null;

  confirmRemove = false;
  removing = false;

  typeLabels = ASSET_TYPE_LABELS;
  assetTypes = ASSET_TYPES;

  countLabel(type: AssetType): string {
    return this.counts[type] === 1 ? ASSET_TYPE_LABELS[type] : PLURALS[type];
  }

  constructor(
    private service: AssetHierarchyService,
    private route: ActivatedRoute
  ) {}

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    this.service.tree().subscribe({
      next: (roots) => {
        this.roots = roots;
        this.counts = emptyCounts();
        const walk = (ns: AssetTreeNode[]) =>
          ns.forEach((n) => {
            this.counts[n.asset_type]++;
            walk(n.children);
          });
        walk(roots);
        if (this.firstLoad) {
          this.firstLoad = false;
          this.collapsed = new Set(
            this.flatten(roots).filter((n) => n.asset_type === 'battery_pack' && n.children.length).map(key)
          );
          this.focusRequested(roots);
        }
        this.applyFilter();
        this.loading = false;
        // keep the selection if the node still exists, else pick the first root
        const all = this.flatten(roots);
        const keep = all.find((n) => key(n) === this.selectedKey) ?? roots[0];
        if (keep) {
          this.select(keep);
        } else {
          this.selectedKey = null;
          this.detail = null;
        }
      },
      error: () => {
        this.error = 'Could not load the asset hierarchy.';
        this.loading = false;
      }
    });
  }

  /** ?type=battery_system&id=1 : select that asset, open its branch and scroll to it. */
  private focusRequested(roots: AssetTreeNode[]): void {
    const params = this.route.snapshot.queryParamMap;
    const wanted = `${params.get('type')}:${params.get('id')}`;
    const path = this.pathTo(roots, wanted);
    if (!path) {
      return;
    }
    path.slice(0, -1).forEach((n) => this.collapsed.delete(key(n)));
    this.selectedKey = wanted;
    setTimeout(() => document.querySelector('.tree-row.selected')?.scrollIntoView({ block: 'center' }));
  }

  private pathTo(ns: AssetTreeNode[], wanted: string): AssetTreeNode[] | null {
    for (const n of ns) {
      if (key(n) === wanted) {
        return [n];
      }
      const below = this.pathTo(n.children, wanted);
      if (below) {
        return [n, ...below];
      }
    }
    return null;
  }

  private flatten(ns: AssetTreeNode[]): AssetTreeNode[] {
    return ns.flatMap((n) => [n, ...this.flatten(n.children)]);
  }

  // ---------------------------------------------------------------- tree

  keyOf = key;

  get searching(): boolean {
    return !!this.searchTerm.trim();
  }

  /** Keep nodes that match, plus the path down to them; a matching node keeps its whole subtree. */
  applyFilter(): void {
    const term = this.searchTerm.trim().toLowerCase();
    if (!term) {
      this.visibleRoots = this.roots;
      return;
    }
    const matches = (n: AssetTreeNode) =>
      [n.asset_name, n.external_id, ASSET_TYPE_LABELS[n.asset_type]].some((v) => v?.toLowerCase().includes(term));
    const prune = (ns: AssetTreeNode[]): AssetTreeNode[] =>
      ns.flatMap((n) => {
        if (matches(n)) {
          return [n];
        }
        const children = prune(n.children);
        return children.length ? [{ ...n, children }] : [];
      });
    this.visibleRoots = prune(this.roots);
  }

  isMatch(n: AssetTreeNode): boolean {
    const term = this.searchTerm.trim().toLowerCase();
    return !!term && [n.asset_name, n.external_id].some((v) => v?.toLowerCase().includes(term));
  }

  isOpen(n: AssetTreeNode): boolean {
    return this.searching || !this.collapsed.has(key(n));
  }

  toggle(n: AssetTreeNode, event: Event): void {
    event.stopPropagation();
    const k = key(n);
    this.collapsed.has(k) ? this.collapsed.delete(k) : this.collapsed.add(k);
  }

  expandAll(): void {
    this.collapsed.clear();
  }

  collapseAll(): void {
    this.collapsed = new Set(this.flatten(this.roots).filter((n) => n.children.length).map(key));
  }

  /** Sites and battery systems at the top level have lost their parent. */
  isOrphan(n: AssetTreeNode, depth: number): boolean {
    return depth === 0 && n.asset_type !== 'tenant';
  }

  // ---------------------------------------------------------------- detail

  select(n: { asset_type: AssetType; source_id: number }): void {
    this.selectedKey = key(n);
    this.detailLoading = true;
    this.service.get(n.asset_type, n.source_id).subscribe({
      next: (d) => {
        this.detail = d;
        this.detailLoading = false;
      },
      error: () => {
        this.detail = null;
        this.detailLoading = false;
      }
    });
  }

  recordLink(type: AssetType, id: number): (string | number)[] {
    return [ASSET_RECORD_ROUTES[type], id];
  }

  // ---------------------------------------------------------------- actions

  sync(): void {
    this.syncing = true;
    this.message = null;
    this.service.sync().subscribe({
      next: (r) => {
        this.syncing = false;
        this.message =
          r.created > 0
            ? `Added ${r.created} missing record${r.created === 1 ? '' : 's'}; refreshed ${r.updated}.`
            : `Hierarchy is up to date (${r.updated} record${r.updated === 1 ? '' : 's'} checked).`;
        this.load();
      },
      error: () => {
        this.syncing = false;
        this.message = 'Sync failed.';
      }
    });
  }

  removeConfirmed(): void {
    if (!this.detail) {
      return;
    }
    const { asset_type, source_id, asset_name } = this.detail;
    this.removing = true;
    this.service.delete(asset_type, source_id).subscribe({
      next: () => {
        this.removing = false;
        this.confirmRemove = false;
        this.selectedKey = null;
        this.message = `Removed "${asset_name}" from the hierarchy. Use "Sync existing records" to add it back.`;
        this.load();
      },
      error: () => {
        this.removing = false;
        this.confirmRemove = false;
      }
    });
  }
}
