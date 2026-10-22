import { Component, inject } from '@angular/core';
import { NavigationEnd, Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { filter, map, startWith } from 'rxjs';

import { AuthService } from '../../core/auth/auth.service';
import { RequestErrorService } from '../../core/observability/request-id';
import { RbacActionsDirective, RbacNavDirective } from '../../core/auth/rbac-ui.directives';

const COLLAPSED_STORAGE_KEY = 'bess.sidenav.collapsed';
const GROUPS_STORAGE_KEY = 'bess.sidenav.groups';
const SECTIONS_STORAGE_KEY = 'bess.sidenav.sections';

// 'dashboard' is the Navigation group (key kept for saved open/closed state); 'insights' is the Dashboard group
// 'ml' is the Insights group (key kept for saved state); 'models' is the ML Model group (training pages)
type NavGroup = 'dashboard' | 'insights' | 'master' | 'telemetry' | 'forecast' | 'analytics' | 'ml' | 'models' | 'batch' | 'admin';
// collapsible sub-groups: Core (master data) -> actor / asset / reference / market / dispatch; Reports -> daily;
// Insights (ML) -> health / anomaly / forecasting / optimization / efficiency / reliability
type NavSection =
  | 'actor'
  | 'asset'
  | 'reference'
  | 'market'
  | 'dispatch'
  | 'fault'
  | 'daily'
  | 'health'
  | 'anomaly'
  | 'forecasting'
  | 'optimization'
  | 'efficiency'
  | 'reliability';

@Component({
  selector: 'app-shell',
  standalone: true,
  imports: [RouterLink, RouterLinkActive, RouterOutlet, RbacNavDirective, RbacActionsDirective],
  templateUrl: './shell.component.html',
  styleUrl: './shell.component.scss'
})
export class ShellComponent {
  readonly auth = inject(AuthService);
  private failures = inject(RequestErrorService);
  forbidden: string | null = null;
  forbiddenRef: string | null = null;
  hideMcp = false;
  private forbiddenTimer: ReturnType<typeof setTimeout> | null = null;
  collapsed = false;
  pageTitle = 'Dashboard';
  activeGroup: NavGroup = 'dashboard';
  openGroups: Record<NavGroup, boolean> = {
    dashboard: true,
    insights: true,
    master: true,
    telemetry: true,
    forecast: true,
    analytics: true,
    ml: true,
    models: true,
    batch: true,
    admin: true
  };
  activeSection: NavSection | null = null;
  openSections: Record<NavSection, boolean> = {
    actor: true,
    asset: true,
    reference: true,
    market: true,
    dispatch: true,
    fault: true,
    daily: true,
    health: true,
    efficiency: true,
    forecasting: true,
    // Insights sub-groups without pages yet start closed
    anomaly: false,
    optimization: true,
    reliability: false
  };

  constructor(private router: Router) {
    // failed API calls (403 / 5xx / unreachable) carry the request id the user can quote; guard refusals have none
    this.failures.failures$.subscribe((f) => this.showBanner(f.message, f.requestId));
    this.auth.forbidden$.subscribe((msg) => this.showBanner(msg, null));

    try {
      this.collapsed = localStorage.getItem(COLLAPSED_STORAGE_KEY) === 'true';
    } catch {
      this.collapsed = false;
    }

    try {
      const saved = JSON.parse(localStorage.getItem(GROUPS_STORAGE_KEY) ?? '{}');
      this.openGroups = { ...this.openGroups, ...saved };
    } catch {
      // keep defaults
    }

    try {
      const saved = JSON.parse(localStorage.getItem(SECTIONS_STORAGE_KEY) ?? '{}');
      this.openSections = { ...this.openSections, ...saved };
    } catch {
      // keep defaults
    }

    this.router.events
      .pipe(
        filter((event): event is NavigationEnd => event instanceof NavigationEnd),
        startWith(null),
        map(() => this.router.url)
      )
      .subscribe((url) => {
        let group: NavGroup;
        if (url.startsWith('/dashboard/operations')) {
          this.pageTitle = 'Dashboard';
          group = 'insights';
        } else if (url.startsWith('/dashboard') || url.startsWith('/plant-view')) {
          this.pageTitle = 'Navigation';
          group = 'dashboard';
        } else if (url.startsWith('/telemetry')) {
          this.pageTitle = 'Live Feed';
          group = 'telemetry';
        } else if (url.startsWith('/forecast-feed')) {
          this.pageTitle = 'Forecast Feed';
          group = 'forecast';
        } else if (url.startsWith('/analytics')) {
          this.pageTitle = 'Daily Summary';
          group = 'analytics';
        } else if (url.startsWith('/ml/training') ||
          url.startsWith('/ml/weak-module-model') ||
          url.startsWith('/ml/mv-anomaly-model') ||
          url.startsWith('/ml/efficiency-model') ||
          url.startsWith('/ml/loss-model') ||
          url.startsWith('/ml/price-forecast-model') ||
          url.startsWith('/ml/soc-forecast-model') ||
          url.startsWith('/ml/soc-estimation-model') ||
          url.startsWith('/ml/thermal-forecast-model') ||
          url.startsWith('/ml/netload-forecast-model') ||
          url.startsWith('/ml/aux-forecast-model') ||
          url.startsWith('/ml/heat-load-model') ||
          url.startsWith('/ml/hvac-cop-model') ||
          url.startsWith('/ml/fault-diag-model') ||
          url.startsWith('/ml/arbitrage-model') ||
          url.startsWith('/ml/rul-model')) {
          this.pageTitle = 'ML Model';
          group = 'models';
        } else if (url.startsWith('/ml')) {
          this.pageTitle = 'Insights';
          group = 'ml';
        } else if (url.startsWith('/batch')) {
          this.pageTitle = 'Batch';
          group = 'batch';
        } else if (url.startsWith('/admin')) {
          this.pageTitle = 'Administration';
          group = 'admin';
        } else {
          this.pageTitle = 'Core';
          group = 'master';
        }
        // keep the group holding the active page visible
        this.activeGroup = group;
        this.openGroups[group] = true;
        // Insights pages: efficiency estimator -> efficiency & performance, price forecast -> forecasting,
        // the rest battery health
        this.activeSection =
          group === 'master'
            ? this.sectionOf(url)
            : group === 'analytics'
              ? 'daily'
              : group === 'ml'
                ? url.startsWith('/ml/efficiency') || url.startsWith('/ml/loss-decomposition') ||
                  (url.startsWith('/ml/heat-load') && !url.startsWith('/ml/heat-load-model')) ||
                  (url.startsWith('/ml/hvac-cop') && !url.startsWith('/ml/hvac-cop-model'))
                  ? 'efficiency'
                  : url.startsWith('/ml/mv-anomaly') || url.startsWith('/ml/fault-diag')
                    ? 'anomaly'
                  : url.startsWith('/ml/arbitrage')
                    ? 'optimization'
                  : url.startsWith('/ml/price-forecast') ||
                    url.startsWith('/ml/soc-forecast') ||
                    url.startsWith('/ml/thermal-forecast') ||
                    url.startsWith('/ml/netload-forecast') ||
                    url.startsWith('/ml/aux-forecast')
                    ? 'forecasting'
                    : 'health'
                : null;
        if (this.activeSection) {
          this.openSections[this.activeSection] = true;
        }
      });
  }

  private showBanner(message: string, requestId: string | null): void {
    this.forbidden = message;
    this.forbiddenRef = requestId;
    if (this.forbiddenTimer) {
      clearTimeout(this.forbiddenTimer);
    }
    this.forbiddenTimer = setTimeout(() => (this.forbidden = this.forbiddenRef = null), requestId ? 15000 : 8000);
  }

  initials(name: string): string {
    const parts = name.replace(/@.*/, '').split(/[\s._-]+/).filter(Boolean);
    return ((parts[0]?.[0] ?? '?') + (parts[1]?.[0] ?? '')).toUpperCase();
  }

  get currentUrl(): string {
    return this.router.url;
  }

  logout(): void {
    void this.auth.logout();
  }

  toggleCollapsed(): void {
    this.collapsed = !this.collapsed;
    try {
      localStorage.setItem(COLLAPSED_STORAGE_KEY, String(this.collapsed));
    } catch {
      // ignore write failures (e.g. private browsing)
    }
  }

  isGroupOpen(group: NavGroup): boolean {
    return this.openGroups[group];
  }

  onGroupClick(group: NavGroup): void {
    if (this.collapsed) {
      // icon-only rail: expand the sidebar and reveal the chosen group
      this.toggleCollapsed();
      this.openGroups[group] = true;
      this.saveGroups();
      return;
    }
    this.toggleGroup(group);
  }

  toggleGroup(group: NavGroup): void {
    this.openGroups[group] = !this.openGroups[group];
    this.saveGroups();
  }

  isSectionOpen(section: NavSection): boolean {
    return this.openSections[section];
  }

  toggleSection(section: NavSection): void {
    this.openSections[section] = !this.openSections[section];
    try {
      localStorage.setItem(SECTIONS_STORAGE_KEY, JSON.stringify(this.openSections));
    } catch {
      // ignore write failures (e.g. private browsing)
    }
  }

  private sectionOf(url: string): NavSection {
    if (url.startsWith('/tenants')) {
      return 'actor';
    }
    if (url.startsWith('/dispatch/')) {
      return 'dispatch';
    }
    if (url.startsWith('/fault/')) {
      return 'fault';
    }
    if (url.startsWith('/dam-prices') || url.startsWith('/rt-prices') || url.startsWith('/as-prices') ||
      url.startsWith('/price-forecasts')) {
      return 'market';
    }
    return url.startsWith('/alarm-catalog') || url.startsWith('/tariff-bands') || url.startsWith('/calendar') ||
      url.startsWith('/aging-snapshots') || url.startsWith('/capacity-tests') ||
      url.startsWith('/lifecycle-events') || url.startsWith('/battery-provenance') ||
      url.startsWith('/ocv-curve') || url.startsWith('/current-sensor-cal') ||
      url.startsWith('/soc-reference')
      ? 'reference'
      : 'asset';
  }

  private saveGroups(): void {
    try {
      localStorage.setItem(GROUPS_STORAGE_KEY, JSON.stringify(this.openGroups));
    } catch {
      // ignore write failures (e.g. private browsing)
    }
  }
}
