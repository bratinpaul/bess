import { CommonModule } from '@angular/common';
import { AfterViewInit, Component, ElementRef, OnDestroy, ViewChild } from '@angular/core';
import { Router } from '@angular/router';
import * as L from 'leaflet';
import { forkJoin } from 'rxjs';

import { DashboardSummary, SiteMapPoint } from '../../../core/models/dashboard.model';
import { DashboardService } from '../../../core/services/dashboard.service';

const INDIA_CENTER: L.LatLngTuple = [22.9734, 78.6569];
const INDIA_DEFAULT_ZOOM = 5;

const siteIcon = L.divIcon({
  className: 'site-marker',
  html: `
    <svg width="28" height="36" viewBox="0 0 28 36" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path d="M14 35S2 21.8 2 13.5A12 12 0 0 1 26 13.5C26 21.8 14 35 14 35Z" fill="#0e8f66" stroke="#ffffff" stroke-width="1.5"/>
      <circle cx="14" cy="13.5" r="5" fill="#63f8ba"/>
    </svg>
  `,
  iconSize: [28, 36],
  iconAnchor: [14, 36],
  popupAnchor: [0, -32]
});

@Component({
  selector: 'app-map-view',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './map-view.component.html',
  styleUrl: './map-view.component.scss'
})
export class MapViewComponent implements AfterViewInit, OnDestroy {
  @ViewChild('mapContainer') mapContainer?: ElementRef<HTMLDivElement>;

  summary: DashboardSummary | null = null;
  sites: SiteMapPoint[] = [];
  loading = true;
  error: string | null = null;

  private map: L.Map | null = null;

  constructor(
    private dashboardService: DashboardService,
    private router: Router
  ) {}

  ngAfterViewInit(): void {
    if (!this.mapContainer) {
      return;
    }
    this.map = L.map(this.mapContainer.nativeElement, {
      center: INDIA_CENTER,
      zoom: INDIA_DEFAULT_ZOOM
    });

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '&copy; OpenStreetMap contributors',
      maxZoom: 18
    }).addTo(this.map);

    this.fetchData();
  }

  ngOnDestroy(): void {
    this.map?.remove();
  }

  private fetchData(): void {
    this.loading = true;
    this.error = null;
    forkJoin({
      summary: this.dashboardService.getSummary(),
      sites: this.dashboardService.getSiteMapPoints()
    }).subscribe({
      next: ({ summary, sites }) => {
        this.summary = summary;
        this.sites = sites;
        this.loading = false;
        this.plotSites(sites);
      },
      error: () => {
        this.error = 'Could not load dashboard data. Is the backend running?';
        this.loading = false;
      }
    });
  }

  private plotSites(sites: SiteMapPoint[]): void {
    if (!this.map || sites.length === 0) {
      return;
    }

    const markers: L.Marker[] = sites.map((site) => {
      const marker = L.marker([site.latitude, site.longitude], { icon: siteIcon });
      marker.bindPopup(`
        <div class="site-popup">
          <strong>${this.escapeHtml(site.site_name)}</strong>
          <div class="site-popup-code">${this.escapeHtml(site.site_code)}</div>
          <div class="site-popup-row"><span>Power</span><span>${site.rated_power_mw ?? '—'} MW</span></div>
          <div class="site-popup-row"><span>Energy</span><span>${site.rated_energy_mwh ?? '—'} MWh</span></div>
          <button type="button" class="btn btn-primary site-popup-3d-btn" data-site-id="${site.site_id}">View in 3D</button>
        </div>
      `);
      marker.on('popupopen', (event) => {
        const popupEl = event.popup.getElement();
        const button = popupEl?.querySelector<HTMLButtonElement>('.site-popup-3d-btn');
        button?.addEventListener('click', () => {
          this.router.navigate(['/plant-view'], { queryParams: { site: site.site_id } });
        });
      });
      marker.addTo(this.map!);
      return marker;
    });

    const group = L.featureGroup(markers);
    this.map.fitBounds(group.getBounds().pad(0.3), { maxZoom: 7 });
  }

  private escapeHtml(value: string): string {
    const div = document.createElement('div');
    div.textContent = value;
    return div.innerHTML;
  }
}
