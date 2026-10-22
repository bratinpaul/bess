import { CommonModule } from '@angular/common';
import { AfterViewInit, Component, ElementRef, NgZone, OnDestroy, ViewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import * as THREE from 'three';
import { forkJoin } from 'rxjs';

import { BatteryContainer } from '../../core/models/battery-container.model';
import { BatteryModule } from '../../core/models/battery-module.model';
import { BatteryPack } from '../../core/models/battery-pack.model';
import { BatterySystem } from '../../core/models/battery-system.model';
import { EmsController } from '../../core/models/ems-controller.model';
import { HvacUnit } from '../../core/models/hvac-unit.model';
import { Pcs } from '../../core/models/pcs.model';
import { Site } from '../../core/models/site.model';
import { BatteryContainerService } from '../../core/services/battery-container.service';
import { BatteryModuleService } from '../../core/services/battery-module.service';
import { BatteryPackService } from '../../core/services/battery-pack.service';
import { BatterySystemService } from '../../core/services/battery-system.service';
import { EmsControllerService } from '../../core/services/ems-controller.service';
import { HvacUnitService } from '../../core/services/hvac-unit.service';
import { PcsService } from '../../core/services/pcs.service';
import { SiteService } from '../../core/services/site.service';

/** The subsystems of the cutaway (each can be shown / hidden). */
export type LayerKey = 'modules' | 'bms' | 'pcs' | 'ems' | 'hvac' | 'fire' | 'shell';
type ComponentType = 'container' | 'pack' | 'module' | 'bms' | 'pcs' | 'ems' | 'hvac' | 'fire';

interface Selected {
  type: ComponentType;
  title: string;
  fields: { label: string; value: string }[];
  /** Optional button in the detail panel that opens a related page. */
  link?: { label: string; route: string; queryParams?: Record<string, string | number> };
}

interface Entry {
  selected: Selected;
  meshes: THREE.Mesh[];
  /** A short note next to the list entry (e.g. module count). */
  note?: string;
}

interface LabelAnchor {
  layer: LayerKey;
  obj: THREE.Object3D;
  local: THREE.Vector3;
  text: string;
  color: string;
  minor?: boolean;
  el?: HTMLDivElement;
}

/* Subsystem colours of the reference cutaway (BESS Container — 3D Cutaway.html). */
const COLORS: Record<LayerKey, number> = {
  modules: 0x3b82f6,
  bms: 0xa78bfa,
  pcs: 0xf97316,
  ems: 0x14b8a6,
  hvac: 0x38bdf8,
  fire: 0xef4444,
  shell: 0x8aa0ab
};
export const LAYER_CSS: Record<LayerKey, string> = {
  modules: '#3b82f6',
  bms: '#a78bfa',
  pcs: '#f97316',
  ems: '#14b8a6',
  hvac: '#38bdf8',
  fire: '#ef4444',
  shell: '#8aa0ab'
};
const TYPE_LAYER: Record<ComponentType, LayerKey> = {
  container: 'shell',
  pack: 'modules',
  module: 'modules',
  bms: 'bms',
  pcs: 'pcs',
  ems: 'ems',
  hvac: 'hvac',
  fire: 'fire'
};
const HIGHLIGHT = 0x2fb3ad;
const SOH_LOW = new THREE.Color(0xc7dcff);
const SOH_HIGH = new THREE.Color(0x1d4ed8);

/* ISO container sizes (m) */
const W = 2.44;
const LEN_20 = 6.06;
const LEN_40 = 12.19;
const H_STD = 2.59;
const H_HC = 2.9;

/* rack geometry (m) */
const RACK_W = 0.82;
const RACK_GAP = 0.16;
const RACK_D = 0.74;
const DOOR_ZONE = 1.15; // master BMS + fire panel at the door end
const POWER_ZONE = 1.7; // PCS + EMS inside the far end
const BASE_Y = 0.24;

interface ContainerLayout {
  L: number;
  H: number;
  sizeLabel: string;
  perBank: number;
  batteryLen: number;
  powerInside: boolean;
  liquid: boolean;
  note: string | null;
}

/**
 * Plant 3D View: an engineering cutaway of each container of the site's battery system, built from master data -
 * one rack per battery pack (with its rack BMS), one module per battery module record, the master BMS with the
 * battery system's data, PCS / EMS cabinets, HVAC units and the container's fire suppression. Subsystems can be
 * toggled or exploded; every component opens its master record.
 */
@Component({
  selector: 'app-plant-view',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  templateUrl: './plant-view.component.html',
  styleUrl: './plant-view.component.scss'
})
export class PlantViewComponent implements AfterViewInit, OnDestroy {
  @ViewChild('canvasHost') canvasHost!: ElementRef<HTMLDivElement>;
  @ViewChild('labelHost') labelHost!: ElementRef<HTMLDivElement>;

  readonly layerCss = LAYER_CSS;
  readonly layerList: { key: LayerKey; label: string }[] = [
    { key: 'modules', label: 'Battery modules' },
    { key: 'bms', label: 'BMS — rack + master' },
    { key: 'pcs', label: 'PCS — inverter' },
    { key: 'ems', label: 'EMS — site controller' },
    { key: 'hvac', label: 'HVAC / thermal' },
    { key: 'fire', label: 'Fire suppression' },
    { key: 'shell', label: 'Container shell' }
  ];

  sites: Site[] = [];
  allSystems: BatterySystem[] = [];
  selectedSiteId: number | null = null;
  selectedSystemId: number | null = null;
  site: Site | null = null;
  batterySystem: BatterySystem | null = null;

  private allContainers: BatteryContainer[] = [];
  private allPacks: BatteryPack[] = [];
  private allModules: BatteryModule[] = [];
  private allPcs: Pcs[] = [];
  private allEms: EmsController[] = [];
  private allHvac: HvacUnit[] = [];

  containers: BatteryContainer[] = [];
  packs: BatteryPack[] = [];
  modules: BatteryModule[] = [];
  pcsList: Pcs[] = [];
  emsList: EmsController[] = [];
  hvacList: HvacUnit[] = [];

  loading = true;
  error: string | null = null;
  selected: Selected | null = null;
  layoutNotes: string[] = [];
  badge = { size: '', energy: '', chemistry: '' };
  counts: Record<LayerKey, string> = { modules: '', bms: '', pcs: '', ems: '', hvac: '', fire: '', shell: '' };

  layers: Record<LayerKey, boolean> = { modules: true, bms: true, pcs: true, ems: true, hvac: true, fire: true, shell: true };
  showLabels = true;
  explode = 0;
  moduleColor: 'type' | 'soh' = 'type';
  sohRange: [number, number] | null = null;

  private scene!: THREE.Scene;
  private camera!: THREE.PerspectiveCamera;
  private renderer!: THREE.WebGLRenderer;
  private root = new THREE.Group();
  private groups = {} as Record<LayerKey, THREE.Group>;
  private explodables: { obj: THREE.Object3D; base: THREE.Vector3; dir: THREE.Vector3 }[] = [];
  private pickables: THREE.Mesh[] = [];
  private anchors: LabelAnchor[] = [];
  private dims: { a: THREE.Vector3; b: THREE.Vector3; text: string; el?: HTMLDivElement }[] = [];
  private highlighted: THREE.Mesh[] = [];
  private moduleMeshes: { mesh: THREE.Mesh; soh: number | null }[] = [];
  private raycaster = new THREE.Raycaster();
  private pointer = new THREE.Vector2();
  private animationHandle = 0;
  private resizeObserver?: ResizeObserver;

  // orbit camera (as in the reference: spherical around a target, right-drag / shift-drag pans)
  private target = new THREE.Vector3();
  private radius = 14;
  private theta = 0.9;
  private phi = 1.05;
  private home = { radius: 14, theta: 0.9, phi: 1.05, target: new THREE.Vector3() };
  private drag: number | null = null;
  private lastX = 0;
  private lastY = 0;
  private downX = 0;
  private downY = 0;
  private readonly onPointerUp = () => (this.drag = null);
  private readonly onPointerMove = (e: PointerEvent) => this.pointerMove(e);

  constructor(
    private route: ActivatedRoute,
    private zone: NgZone,
    private siteService: SiteService,
    private batterySystemService: BatterySystemService,
    private containerService: BatteryContainerService,
    private packService: BatteryPackService,
    private moduleService: BatteryModuleService,
    private pcsService: PcsService,
    private emsService: EmsControllerService,
    private hvacService: HvacUnitService
  ) {}

  ngAfterViewInit(): void {
    this.zone.runOutsideAngular(() => {
      this.initScene();
      this.animate();
    });

    const siteParam = this.route.snapshot.queryParamMap.get('site');
    const requestedSiteId = siteParam ? Number(siteParam) : null;

    forkJoin({
      sites: this.siteService.list(),
      systems: this.batterySystemService.list(),
      containers: this.containerService.list(),
      packs: this.packService.list(),
      modules: this.moduleService.list(),
      pcs: this.pcsService.list(),
      ems: this.emsService.list(),
      hvac: this.hvacService.list()
    }).subscribe({
      next: (r) => {
        this.sites = r.sites;
        this.allSystems = r.systems;
        this.allContainers = r.containers;
        this.allPacks = r.packs;
        this.allModules = r.modules;
        this.allPcs = r.pcs;
        this.allEms = r.ems;
        this.allHvac = r.hvac;
        const withSystem = (id: number) => r.systems.some((s) => s.site_id === id);
        this.selectedSiteId =
          requestedSiteId && r.sites.some((s) => s.site_id === requestedSiteId)
            ? requestedSiteId
            : r.sites.find((s) => withSystem(s.site_id))?.site_id ?? r.sites[0]?.site_id ?? null;
        this.loading = false;
        this.onSiteChange();
      },
      error: () => {
        this.error = 'Could not load plant data. Is the backend running?';
        this.loading = false;
      }
    });
  }

  ngOnDestroy(): void {
    cancelAnimationFrame(this.animationHandle);
    this.resizeObserver?.disconnect();
    window.removeEventListener('pointerup', this.onPointerUp);
    window.removeEventListener('pointermove', this.onPointerMove);
    this.disposeRoot();
    this.renderer?.dispose();
  }

  get siteSystems(): BatterySystem[] {
    return this.allSystems.filter((s) => s.site_id === this.selectedSiteId);
  }

  onSiteChange(): void {
    this.site = this.sites.find((s) => s.site_id === this.selectedSiteId) ?? null;
    this.selectedSystemId = this.siteSystems[0]?.battery_system_id ?? null;
    this.onSystemChange();
  }

  onSystemChange(): void {
    const sys = this.allSystems.find((s) => s.battery_system_id === this.selectedSystemId) ?? null;
    this.batterySystem = sys;
    this.containers = sys ? this.allContainers.filter((c) => c.battery_system_id === sys.battery_system_id) : [];
    const containerIds = new Set(this.containers.map((c) => c.container_id));
    this.packs = this.allPacks
      .filter((p) => containerIds.has(p.container_id))
      .sort((a, b) => (a.pack_number ?? '').localeCompare(b.pack_number ?? '', undefined, { numeric: true }) || a.pack_id - b.pack_id);
    const packIds = new Set(this.packs.map((p) => p.pack_id));
    this.modules = this.allModules
      .filter((m) => packIds.has(m.pack_id))
      .sort((a, b) => (a.serial_number ?? '').localeCompare(b.serial_number ?? '', undefined, { numeric: true }) || a.module_id - b.module_id);
    this.pcsList = sys ? this.allPcs.filter((p) => p.system_id === sys.battery_system_id) : [];
    this.emsList = sys ? this.allEms.filter((e) => e.battery_system_id === sys.battery_system_id) : [];
    this.hvacList = sys ? this.allHvac.filter((h) => h.battery_system_id === sys.battery_system_id) : [];
    this.selected = null;
    this.buildPlant();
  }

  closeDetail(): void {
    this.selected = null;
    this.setHighlight([]);
  }

  // ---------------------------------------------------------------- view controls

  toggleLayer(key: LayerKey): void {
    this.layers[key] = !this.layers[key];
    this.groups[key].visible = this.layers[key];
  }

  setExplode(v: number): void {
    this.explode = Number(v);
    const t = this.explode / 100;
    for (const e of this.explodables) {
      e.obj.position.copy(e.base).addScaledVector(e.dir, t);
    }
  }

  setModuleColor(mode: 'type' | 'soh'): void {
    this.moduleColor = mode;
    this.paintModules();
  }

  resetView(): void {
    this.radius = this.home.radius;
    this.theta = this.home.theta;
    this.phi = this.home.phi;
    this.target.copy(this.home.target);
    this.applyCamera();
    this.setExplode(0);
  }

  // ---------------------------------------------------------------- scene

  private initScene(): void {
    const host = this.canvasHost.nativeElement;
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x0b1014);
    this.scene.fog = new THREE.Fog(0x0b1014, 32, 75);

    this.camera = new THREE.PerspectiveCamera(42, this.aspect(), 0.1, 250);
    this.renderer = new THREE.WebGLRenderer({ antialias: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.setSize(host.clientWidth, host.clientHeight);
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    host.appendChild(this.renderer.domElement);

    this.scene.add(new THREE.AmbientLight(0xafc0cc, 0.6));
    const key = new THREE.DirectionalLight(0xffffff, 0.95);
    key.position.set(10, 18, 12);
    key.castShadow = true;
    key.shadow.mapSize.set(2048, 2048);
    Object.assign(key.shadow.camera, { left: -20, right: 20, top: 20, bottom: -20 });
    this.scene.add(key);
    const fill = new THREE.DirectionalLight(0x6fb6ff, 0.35);
    fill.position.set(-12, 8, -6);
    this.scene.add(fill);

    const grid = new THREE.GridHelper(80, 80, 0x2a3a44, 0x172127);
    this.scene.add(grid);
    const ground = new THREE.Mesh(new THREE.PlaneGeometry(80, 80), new THREE.MeshStandardMaterial({ color: 0x0e151a, roughness: 1 }));
    ground.rotation.x = -Math.PI / 2;
    ground.position.y = -0.01;
    ground.receiveShadow = true;
    this.scene.add(ground);
    this.scene.add(this.root);

    const canvas = this.renderer.domElement;
    canvas.addEventListener('pointerdown', (e) => {
      this.drag = e.button;
      this.lastX = this.downX = e.clientX;
      this.lastY = this.downY = e.clientY;
    });
    window.addEventListener('pointerup', this.onPointerUp);
    window.addEventListener('pointermove', this.onPointerMove);
    canvas.addEventListener(
      'wheel',
      (e) => {
        e.preventDefault();
        this.radius = Math.max(4, Math.min(70, this.radius + e.deltaY * 0.02));
        this.applyCamera();
      },
      { passive: false }
    );
    canvas.addEventListener('contextmenu', (e) => e.preventDefault());
    canvas.addEventListener('click', (e) => {
      if (Math.hypot(e.clientX - this.downX, e.clientY - this.downY) < 5) {
        this.pick(e);
      }
    });

    this.resizeObserver = new ResizeObserver(() => this.onResize());
    this.resizeObserver.observe(host);
    this.applyCamera();
  }

  private aspect(): number {
    const host = this.canvasHost.nativeElement;
    return (host.clientWidth || 1) / (host.clientHeight || 1);
  }

  private onResize(): void {
    const host = this.canvasHost.nativeElement;
    if (!host.clientWidth || !host.clientHeight) {
      return;
    }
    this.camera.aspect = host.clientWidth / host.clientHeight;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(host.clientWidth, host.clientHeight);
  }

  private applyCamera(): void {
    const t = this.target;
    this.camera.position.set(
      t.x + this.radius * Math.sin(this.phi) * Math.cos(this.theta),
      t.y + this.radius * Math.cos(this.phi),
      t.z + this.radius * Math.sin(this.phi) * Math.sin(this.theta)
    );
    this.camera.lookAt(t);
  }

  private pointerMove(e: PointerEvent): void {
    if (this.drag === null) {
      return;
    }
    const dx = e.clientX - this.lastX;
    const dy = e.clientY - this.lastY;
    this.lastX = e.clientX;
    this.lastY = e.clientY;
    if (this.drag === 2 || e.shiftKey) {
      const right = new THREE.Vector3().subVectors(this.camera.position, this.target).cross(this.camera.up).normalize();
      this.target.addScaledVector(right, -dx * 0.012 * (this.radius / 14));
      this.target.y = Math.max(0, this.target.y + dy * 0.012 * (this.radius / 14));
    } else {
      this.theta -= dx * 0.006;
      this.phi = Math.max(0.2, Math.min(1.48, this.phi - dy * 0.006));
    }
    this.applyCamera();
  }

  private animate = (): void => {
    this.animationHandle = requestAnimationFrame(this.animate);
    this.renderer.render(this.scene, this.camera);
    this.updateLabels();
  };

  private pick(event: MouseEvent): void {
    const rect = this.renderer.domElement.getBoundingClientRect();
    this.pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    this.pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
    this.raycaster.setFromCamera(this.pointer, this.camera);
    const hits = this.raycaster.intersectObjects(this.pickables, false).filter((h) => this.isShown(h.object));
    const mesh = hits[0]?.object as THREE.Mesh | undefined;
    const entry = mesh?.userData['entry'] as Entry | undefined;
    this.zone.run(() => {
      if (entry) {
        this.selected = entry.selected;
        this.setHighlight(entry.selected.type === 'module' ? [mesh!] : entry.meshes);
      }
    });
  }

  private isShown(obj: THREE.Object3D): boolean {
    for (let o: THREE.Object3D | null = obj; o; o = o.parent) {
      if (!o.visible) {
        return false;
      }
    }
    return true;
  }

  private setHighlight(meshes: THREE.Mesh[]): void {
    for (const m of this.highlighted) {
      const mat = m.material as THREE.MeshStandardMaterial;
      mat.emissive.setHex(0x000000);
      mat.emissiveIntensity = 1;
    }
    this.highlighted = meshes;
    for (const m of meshes) {
      const mat = m.material as THREE.MeshStandardMaterial;
      mat.emissive.setHex(HIGHLIGHT);
      mat.emissiveIntensity = 0.55;
    }
  }

  // ---------------------------------------------------------------- labels

  private updateLabels(): void {
    const host = this.canvasHost?.nativeElement;
    if (!host) {
      return;
    }
    const w = host.clientWidth;
    const h = host.clientHeight;
    const v = new THREE.Vector3();
    for (const a of this.anchors) {
      const el = a.el;
      if (!el) {
        continue;
      }
      if (!this.showLabels || !this.layers[a.layer] || (a.minor && this.radius > 26)) {
        el.style.display = 'none';
        continue;
      }
      a.obj.localToWorld(v.copy(a.local));
      v.project(this.camera);
      if (v.z > 1 || Math.abs(v.x) > 1.1 || Math.abs(v.y) > 1.1) {
        el.style.display = 'none';
        continue;
      }
      el.style.display = 'block';
      el.style.left = `${(v.x * 0.5 + 0.5) * w}px`;
      el.style.top = `${(-v.y * 0.5 + 0.5) * h}px`;
    }
    for (const d of this.dims) {
      if (!d.el) {
        continue;
      }
      v.copy(d.a).add(d.b).multiplyScalar(0.5).project(this.camera);
      const show = this.showLabels && this.layers.shell && v.z <= 1;
      d.el.style.display = show ? 'block' : 'none';
      if (show) {
        d.el.style.left = `${(v.x * 0.5 + 0.5) * w}px`;
        d.el.style.top = `${(-v.y * 0.5 + 0.5) * h}px`;
      }
    }
  }

  private renderLabelElements(): void {
    const host = this.labelHost.nativeElement;
    host.innerHTML = '';
    for (const a of this.anchors) {
      const el = document.createElement('div');
      el.className = a.minor ? 'cut-lab minor' : 'cut-lab';
      const dot = document.createElement('span');
      dot.className = 'd';
      dot.style.background = a.color;
      el.appendChild(dot);
      el.appendChild(document.createTextNode(a.text));
      host.appendChild(el);
      a.el = el;
    }
    for (const d of this.dims) {
      const el = document.createElement('div');
      el.className = 'cut-dim';
      el.textContent = d.text;
      host.appendChild(el);
      d.el = el;
    }
  }

  // ---------------------------------------------------------------- building

  private disposeRoot(): void {
    this.root.traverse((o) => {
      const m = o as THREE.Mesh;
      m.geometry?.dispose?.();
      const mat = m.material as THREE.Material | THREE.Material[] | undefined;
      (Array.isArray(mat) ? mat : mat ? [mat] : []).forEach((x) => x.dispose());
    });
    this.root.clear();
  }

  private mat(color: number, o: { m?: number; r?: number; opacity?: number; flat?: boolean } = {}): THREE.MeshStandardMaterial {
    return new THREE.MeshStandardMaterial({
      color,
      metalness: o.m ?? 0.35,
      roughness: o.r ?? 0.55,
      transparent: o.opacity !== undefined,
      opacity: o.opacity ?? 1,
      flatShading: o.flat ?? false,
      depthWrite: o.opacity === undefined || o.opacity > 0.5
    });
  }

  /** A box by its centre. */
  private box(parent: THREE.Object3D, cx: number, cy: number, cz: number, w: number, h: number, d: number, color: number,
              o: { m?: number; r?: number; opacity?: number; flat?: boolean; noShadow?: boolean } = {}): THREE.Mesh {
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), this.mat(color, o));
    mesh.position.set(cx, cy, cz);
    mesh.castShadow = !o.noShadow;
    mesh.receiveShadow = true;
    parent.add(mesh);
    return mesh;
  }

  private edges(parent: THREE.Object3D, cx: number, cy: number, cz: number, w: number, h: number, d: number, color: number): void {
    const l = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(w, h, d)), new THREE.LineBasicMaterial({ color }));
    l.position.set(cx, cy, cz);
    parent.add(l);
  }

  private cylinder(parent: THREE.Object3D, x: number, y: number, z: number, r: number, h: number, color: number, rot?: 'x' | 'z'): THREE.Mesh {
    const m = new THREE.Mesh(new THREE.CylinderGeometry(r, r, h, 18), this.mat(color, { m: 0.45, r: 0.4 }));
    m.position.set(x, y, z);
    if (rot === 'z') {
      m.rotation.z = Math.PI / 2;
    } else if (rot === 'x') {
      m.rotation.x = Math.PI / 2;
    }
    m.castShadow = true;
    parent.add(m);
    return m;
  }

  private explodable(obj: THREE.Object3D, dir: THREE.Vector3): void {
    this.explodables.push({ obj, base: obj.position.clone(), dir });
  }

  private pickable(mesh: THREE.Mesh, entry: Entry): void {
    mesh.userData['entry'] = entry;
    entry.meshes.push(mesh);
    this.pickables.push(mesh);
  }

  private label(layer: LayerKey, obj: THREE.Object3D, local: THREE.Vector3, text: string, minor = false): void {
    this.anchors.push({ layer, obj, local, text, color: LAYER_CSS[layer], minor });
  }

  /** Container length / height from its type ("20ft …", "40ft …", high cube), else the smallest ISO size the racks fit. */
  private layoutOf(c: BatteryContainer, packCount: number): ContainerLayout {
    const type = (c.container_type ?? '').toLowerCase();
    const perBank = Math.max(1, Math.ceil(packCount / 2));
    const batteryLen = DOOR_ZONE + perBank * (RACK_W + RACK_GAP);
    const needInside = batteryLen + POWER_ZONE + 0.15;
    let L: number;
    let sizeLabel: string;
    let note: string | null = null;
    if (/40\s*(ft|'|foot|feet)/.test(type)) {
      L = LEN_40;
      sizeLabel = '40 ft';
    } else if (/20\s*(ft|'|foot|feet)/.test(type)) {
      L = LEN_20;
      sizeLabel = '20 ft';
    } else {
      L = needInside <= LEN_20 ? LEN_20 : needInside <= LEN_40 ? LEN_40 : needInside;
      sizeLabel = L === LEN_20 ? '20 ft (assumed)' : L === LEN_40 ? '40 ft (assumed)' : `${L.toFixed(1)} m (assumed)`;
      note = `${c.container_number ?? 'Container'}: no size in container_type - drawn as ${sizeLabel}`;
    }
    if (batteryLen + 0.1 > L) {
      note = `${c.container_number ?? 'Container'}: ${packCount} racks don't fit a ${sizeLabel} container - drawn ${batteryLen.toFixed(1)} m long`;
      L = batteryLen + 0.1;
    }
    const H = /high\s*cube|\bhc\b/.test(type) ? H_HC : H_STD;
    const liquid = /liquid/.test(type) || this.pcsList.some((p) => /liquid/i.test(p.cooling ?? ''));
    return { L, H, sizeLabel, perBank, batteryLen, powerInside: L - batteryLen - 0.1 >= POWER_ZONE, liquid, note };
  }

  private buildPlant(): void {
    if (!this.scene) {
      return;
    }
    this.disposeRoot();
    this.explodables = [];
    this.pickables = [];
    this.anchors = [];
    this.dims = [];
    this.highlighted = [];
    this.moduleMeshes = [];
    this.layoutNotes = [];
    for (const k of Object.keys(COLORS) as LayerKey[]) {
      const g = new THREE.Group();
      g.visible = this.layers[k];
      this.groups[k] = g;
      this.root.add(g);
    }
    const sys = this.batterySystem;
    const sections: Record<string, Entry[]> = { System: [], Containers: [], Packs: [], 'Power & control': [], Thermal: [], Safety: [] };

    // the master BMS carries the battery system's data (one per system)
    const bmsEntry: Entry = { selected: this.bmsSelection(), meshes: [] };
    if (sys) {
      sections['System'].push(bmsEntry);
    }

    const containers = this.containers.length ? this.containers : [];
    let zOffset = 0;
    let maxL = 0;
    let firstLayout: ContainerLayout | null = null;
    const pcsEntries = this.pcsList.map((p) => ({ selected: this.pcsSelection(p), meshes: [] as THREE.Mesh[] }) as Entry);
    const emsEntries = this.emsList.map((e) => ({ selected: this.emsSelection(e), meshes: [] as THREE.Mesh[] }) as Entry);
    const hvacEntries = this.hvacList.map((h) => ({ selected: this.hvacSelection(h), meshes: [] as THREE.Mesh[] }) as Entry);

    containers.forEach((c, ci) => {
      const packs = this.packs.filter((p) => p.container_id === c.container_id);
      const lay = this.layoutOf(c, packs.length);
      firstLayout ??= lay;
      if (lay.note) {
        this.layoutNotes.push(lay.note);
      }
      maxL = Math.max(maxL, lay.L);
      const origin = new THREE.Vector3(0, 0, zOffset);
      const cEntry: Entry = { selected: this.containerSelection(c, lay, packs.length), meshes: [], note: lay.sizeLabel };
      sections['Containers'].push(cEntry);
      this.buildShell(origin, lay, cEntry);
      this.buildRacks(origin, lay, packs, sections['Packs'], ci === 0 ? bmsEntry : null);
      if (ci === 0) {
        this.buildMasterBms(origin, lay, bmsEntry);
        this.buildPower(origin, lay, pcsEntries, emsEntries);
        this.buildHvac(origin, lay, hvacEntries);
      }
      const fire = this.buildFire(origin, lay, c);
      if (fire) {
        sections['Safety'].push(fire);
      }
      zOffset += W + (lay.powerInside ? 3 : 3.5);
    });

    sections['Power & control'].push(...pcsEntries, ...emsEntries);
    sections['Thermal'].push(...hvacEntries);
    if (!containers.length) {
      this.layoutNotes.push(sys ? 'This battery system has no container in master data.' : 'This site has no battery system in master data.');
    }
    if (sys && !this.pcsList.length) {
      this.layoutNotes.push('No PCS in master data for this battery system.');
    }

    // counts and badge
    const fireTypes = Array.from(new Set(containers.map((c) => c.fire_suppression).filter((f): f is string => !!f)));
    this.counts = {
      modules: `${this.modules.length} mod`,
      bms: `${this.packs.length + (sys ? 1 : 0)}`,
      pcs: `${this.pcsList.length}`,
      ems: `${this.emsList.length}`,
      hvac: `${this.hvacList.length}`,
      fire: fireTypes.length ? fireTypes.join(', ') : 'not recorded',
      shell: `${containers.length}`
    };
    const lay0 = firstLayout as ContainerLayout | null;
    this.badge = {
      size: containers.length ? `${containers.length} × ${lay0?.sizeLabel ?? ''} container${lay0?.liquid ? ' · liquid-cooled' : ''}` : 'No container',
      energy: sys ? `${this.num(sys.rated_power_mw)} MW / ${this.num(sys.rated_energy_mwh)} MWh` : '—',
      chemistry: sys ? `${sys.chemistry_code ?? '—'} · ${sys.series_cells ?? '—'}S${sys.parallel_cells ?? '—'}P · ${this.num(sys.nominal_dc_voltage, 0)} V DC` : ''
    };
    const sohs = this.modules.map((m) => (m.soh_pct === null ? null : Number(m.soh_pct))).filter((v): v is number => v !== null && Number.isFinite(v));
    this.sohRange = sohs.length ? [Math.min(...sohs), Math.max(...sohs)] : null;
    if (!this.sohRange && this.moduleColor === 'soh') {
      this.moduleColor = 'type';
    }
    this.paintModules();

    // camera framing
    const span = Math.max(maxL + (lay0 && !lay0.powerInside ? 4 : 0), zOffset, 6);
    this.target.set((maxL || 6) / 2 + (lay0 && !lay0.powerInside ? 1.5 : 0), 1.1, Math.max(zOffset - 3, W) / 2);
    this.radius = Math.max(12, span * 1.9);
    this.theta = 0.95;
    this.phi = 1.0;
    this.applyCamera();
    // the subsystem panel covers the left of the canvas: aim a little left so the model sits right of centre
    const right = new THREE.Vector3().subVectors(this.camera.position, this.target).cross(this.camera.up).normalize();
    this.target.addScaledVector(right, this.radius * 0.1);
    this.home = { radius: this.radius, theta: this.theta, phi: this.phi, target: this.target.clone() };
    this.applyCamera();
    this.renderLabelElements();
    this.setExplode(this.explode);
  }

  private buildShell(o: THREE.Vector3, lay: ContainerLayout, entry: Entry): void {
    const g = new THREE.Group();
    g.position.copy(o);
    this.groups.shell.add(g);
    const { L, H } = lay;
    const steel = COLORS.shell;
    const floor = this.box(g, L / 2, 0.06, W / 2, L, 0.12, W, steel, { opacity: 0.92, r: 0.8, m: 0.2 });
    this.pickable(floor, entry);
    const wall = { opacity: 0.07, r: 0.6, m: 0.5, noShadow: true };
    this.pickable(this.box(g, L / 2, H / 2, 0.04, L, H, 0.08, steel, wall), entry);
    this.pickable(this.box(g, 0.04, H / 2, W / 2, 0.08, H, W, steel, wall), entry);
    this.pickable(this.box(g, L - 0.04, H / 2, W / 2, 0.08, H, W, steel, wall), entry);
    const roof = new THREE.Group();
    g.add(roof);
    this.pickable(this.box(roof, L / 2, H, W / 2, L, 0.1, W, steel, { opacity: 0.16, r: 0.5, m: 0.6, noShadow: true }), entry);
    this.explodable(roof, new THREE.Vector3(0, 2.6, 0));
    this.edges(g, L / 2, H / 2, W / 2, L, H, W, 0x3a4c57);
    for (const [x, z] of [[0, 0], [L, 0], [0, W], [L, W]]) {
      this.box(g, x, H / 2, z, 0.14, H, 0.14, steel, { opacity: 0.9, r: 0.6, m: 0.5, noShadow: true });
    }
    this.edges(g, 0.09, H / 2 - 0.1, W / 2, 0.02, H - 0.4, W - 0.5, 0x4a5c67); // door on the left end
    this.label('shell', g, new THREE.Vector3(L * 0.5, H + 0.25, 0.1), entry.selected.title, true);
    if (!this.dims.length) {
      this.dims.push(
        { a: new THREE.Vector3(0, -0.3, W + 0.4).add(o), b: new THREE.Vector3(L, -0.3, W + 0.4).add(o), text: `${L.toFixed(2)} m` },
        { a: new THREE.Vector3(L + 0.4, 0, W + 0.1).add(o), b: new THREE.Vector3(L + 0.4, H, W + 0.1).add(o), text: `${H.toFixed(2)} m` }
      );
    }
  }

  /** One rack per pack in two banks along the long walls; one module per module record; a rack BMS on top. */
  private buildRacks(o: THREE.Vector3, lay: ContainerLayout, packs: BatteryPack[], packEntries: Entry[], bmsEntry: Entry | null): void {
    const banks = [
      { z: 0.55, dir: -1, packs: packs.slice(0, lay.perBank) },
      { z: W - 0.55, dir: 1, packs: packs.slice(lay.perBank) }
    ];
    const usable = lay.H - BASE_Y - 0.62; // room above for rack BMS, manifolds / ducts
    for (const bank of banks) {
      if (!bank.packs.length) {
        continue;
      }
      const mg = new THREE.Group();
      const bg = new THREE.Group();
      mg.position.copy(o);
      bg.position.copy(o);
      this.groups.modules.add(mg);
      this.groups.bms.add(bg);
      const dir = new THREE.Vector3(0, 0, bank.dir * 1.4);
      this.explodable(mg, dir);
      this.explodable(bg, dir);
      bank.packs.forEach((pack, r) => {
        const cx = DOOR_ZONE + r * (RACK_W + RACK_GAP) + RACK_W / 2;
        const mods = this.modules.filter((m) => m.pack_id === pack.pack_id);
        const n = mods.length;
        const cols = n > 10 ? 2 : 1;
        const rows = Math.max(1, Math.ceil(n / cols));
        const modH = Math.min(0.32, usable / rows);
        const rackH = n ? rows * modH : usable;
        const entry: Entry = { selected: this.packSelection(pack, mods), meshes: [], note: `${n} mod` };
        packEntries.push(entry);
        // rack frame + plinth
        this.edges(mg, cx, BASE_Y + rackH / 2, bank.z, RACK_W + 0.06, rackH + 0.1, RACK_D, 0x3a4c57);
        this.pickable(this.box(mg, cx, BASE_Y - 0.05, bank.z, RACK_W + 0.06, 0.1, RACK_D, 0x24313a, { r: 0.8 }), entry);
        if (!n) {
          // a pack without module records: an empty rack
          this.pickable(this.box(mg, cx, BASE_Y + rackH / 2, bank.z, RACK_W, rackH, RACK_D - 0.06, COLORS.modules, { opacity: 0.08, noShadow: true }), entry);
          this.label('modules', mg, new THREE.Vector3(cx, BASE_Y + rackH / 2, bank.z), `${this.short(pack.pack_number)} · no modules in master data`, true);
        }
        const mw = (RACK_W - 0.02 * (cols - 1)) / cols;
        mods.forEach((m, i) => {
          const row = Math.floor(i / cols);
          const col = i % cols;
          const mx = cx - RACK_W / 2 + mw / 2 + col * (mw + 0.02);
          const my = BASE_Y + row * modH + modH / 2;
          const mesh = this.box(mg, mx, my, bank.z, mw, modH - 0.03, RACK_D - 0.06, COLORS.modules, { m: 0.3, r: 0.5, flat: true });
          const mEntry: Entry = { selected: this.moduleSelection(m, pack), meshes: [] };
          mesh.userData['entry'] = mEntry;
          mEntry.meshes.push(mesh);
          this.pickables.push(mesh);
          entry.meshes.push(mesh);
          this.moduleMeshes.push({ mesh, soh: m.soh_pct === null ? null : Number(m.soh_pct) });
        });
        // rack BMS (slave) on top
        const slave = this.box(bg, cx, BASE_Y + rackH + 0.13, bank.z, RACK_W * 0.55, 0.14, 0.4, COLORS.bms, { flat: true });
        this.pickable(slave, { selected: this.rackBmsSelection(pack, n), meshes: [] });
        if (bmsEntry) {
          bmsEntry.meshes.push(slave);
        }
        this.label('modules', mg, new THREE.Vector3(cx, BASE_Y + rackH + 0.35, bank.z), this.short(pack.pack_number), true);
      });
      const first = bank.packs.length;
      const total = bank.packs.reduce((s, p) => s + this.modules.filter((m) => m.pack_id === p.pack_id).length, 0);
      const mid = DOOR_ZONE + (first * (RACK_W + RACK_GAP)) / 2;
      this.label('modules', mg, new THREE.Vector3(mid, BASE_Y + usable * 0.55, bank.z + bank.dir * 0.42),
        `${this.short(bank.packs[0].pack_number)}–${this.short(bank.packs[first - 1].pack_number)} · ${total} modules`);
    }
  }

  private buildMasterBms(o: THREE.Vector3, lay: ContainerLayout, entry: Entry): void {
    if (!this.batterySystem) {
      return;
    }
    const g = new THREE.Group();
    g.position.copy(o);
    this.groups.bms.add(g);
    this.explodable(g, new THREE.Vector3(-1.2, 0, 0));
    const cab = this.box(g, 0.62, 1.05, W / 2, 0.42, 1.8, 0.36, COLORS.bms, { flat: true });
    this.box(g, 0.62 + 0.22, 1.35, W / 2, 0.02, 0.3, 0.24, 0xe9e2ff, { noShadow: true, opacity: 0.9 });
    this.pickable(cab, entry);
    this.label('bms', g, new THREE.Vector3(0.62, 2.1, W / 2), `Master BMS · ${this.batterySystem.bms_firmware ?? 'firmware n/a'}`);
  }

  /** PCS and EMS cabinets in the power end of the container, or on a skid beside it when they don't fit. */
  private buildPower(o: THREE.Vector3, lay: ContainerLayout, pcsEntries: Entry[], emsEntries: Entry[]): void {
    const nP = this.pcsList.length;
    const nE = this.emsList.length;
    if (!nP && !nE) {
      return;
    }
    const pcsW = 1.25;
    const emsW = 0.5;
    const insideFits = lay.powerInside && nP <= 1 && nE <= 1;
    const pg = new THREE.Group();
    const eg = new THREE.Group();
    pg.position.copy(o);
    eg.position.copy(o);
    this.groups.pcs.add(pg);
    this.groups.ems.add(eg);
    let x0: number;
    if (insideFits) {
      x0 = lay.batteryLen + 0.15 + Math.max(0, (lay.L - lay.batteryLen - 0.25 - pcsW) / 2);
      this.explodable(pg, new THREE.Vector3(2.2, 0, 0));
      this.explodable(eg, new THREE.Vector3(2.2, 0.4, 0));
    } else {
      // external power skid with a cable tray from the container end
      x0 = lay.L + 1.4;
      const skidLen = Math.max(nP * (pcsW + 0.25), 1) + (nE ? emsW + 0.4 : 0) + 0.4;
      this.box(pg, x0 + skidLen / 2 - 0.2, 0.08, W / 2, skidLen, 0.16, W + 0.4, 0x2a3640, { r: 0.9, m: 0.1 });
      this.box(pg, (lay.L + x0) / 2 - 0.1, 0.3, W / 2, x0 - lay.L + 0.2, 0.08, 0.35, 0x6b5a46, { m: 0.5 });
      this.explodable(pg, new THREE.Vector3(1.5, 0, 0));
      this.explodable(eg, new THREE.Vector3(1.5, 0.4, 0));
      this.layoutNotes.push(
        `${nP} PCS${nE ? ` and ${nE} EMS` : ''} drawn on a power skid beside the container (no room in its power end).`
      );
    }
    this.pcsList.forEach((p, i) => {
      const x = insideFits ? x0 + pcsW / 2 : x0 + i * (pcsW + 0.25) + pcsW / 2;
      const z = insideFits ? 0.62 : W / 2 - 0.35;
      const cab = this.box(pg, x, 1.12, z, pcsW, 2.05, 0.92, COLORS.pcs, { m: 0.4, r: 0.4, flat: true });
      this.edges(pg, x, 1.12, z, pcsW, 2.05, 0.92, 0x7a4010);
      for (let k = 0; k < 4; k++) {
        this.box(pg, x, 1.7 - k * 0.28, z + 0.47, pcsW * 0.78, 0.04, 0.02, 0x2a1a0a, { noShadow: true });
      }
      this.pickable(cab, pcsEntries[i]);
      this.label('pcs', pg, new THREE.Vector3(x, 2.35, z), `${p.pcs_code} · ${this.num(p.rated_power_kw, 0)} kW`);
    });
    const ex = insideFits ? x0 + pcsW / 2 : x0 + nP * (pcsW + 0.25) + emsW / 2 + 0.1;
    this.emsList.forEach((e, i) => {
      const z = insideFits ? W - 0.5 : W / 2 - 0.35 + i * 0.6;
      const cab = this.box(eg, ex, 0.98, z, emsW, 1.75, 0.4, COLORS.ems, { m: 0.4, r: 0.4, flat: true });
      this.box(eg, ex + emsW / 2 + 0.01, 1.32, z, 0.02, 0.34, 0.28, 0x0affd0, { noShadow: true, opacity: 0.9 });
      this.pickable(cab, emsEntries[i]);
      this.label('ems', eg, new THREE.Vector3(ex, 1.95 + i * 0.3, z), `${e.ems_code}${e.control_mode ? ' · ' + e.control_mode : ''}`);
    });
  }

  /** One roof unit per HVAC record, plus coolant manifolds (liquid-cooled) or an air duct with drops. */
  private buildHvac(o: THREE.Vector3, lay: ContainerLayout, entries: Entry[]): void {
    if (!this.hvacList.length) {
      return;
    }
    const g = new THREE.Group();
    g.position.copy(o);
    this.groups.hvac.add(g);
    this.explodable(g, new THREE.Vector3(0, 2.0, 0));
    const { L, H } = lay;
    const n = this.hvacList.length;
    const span = Math.min(lay.batteryLen, L) - 0.6;
    this.hvacList.forEach((h, i) => {
      const x = 0.6 + (span * (i + 0.5)) / n + 0.3;
      const unit = this.box(g, x, H + 0.27, W / 2, 1.1, 0.5, 0.95, COLORS.hvac, { m: 0.4, r: 0.4, flat: true });
      this.cylinder(g, x, H + 0.53, W / 2, 0.32, 0.03, 0x0a2733);
      this.pickable(unit, entries[i]);
      this.label('hvac', g, new THREE.Vector3(x, H + 0.75, W / 2),
        `${h.hvac_code}${h.cooling_capacity_kw ? ' · ' + this.num(h.cooling_capacity_kw, 0) + ' kW' : ''}`);
    });
    const runFrom = DOOR_ZONE - 0.1;
    const runTo = lay.batteryLen - 0.05;
    const len = Math.max(runTo - runFrom, 0.5);
    if (lay.liquid) {
      // supply / return coolant manifolds along the back of each bank, with a drop to every rack
      for (const z of [0.12, W - 0.12]) {
        const supply = this.cylinder(g, runFrom + len / 2, H - 0.42, z, 0.045, len, 0x38bdf8, 'z');
        const ret = this.cylinder(g, runFrom + len / 2, H - 0.56, z, 0.045, len, 0x1e6f99, 'z');
        entries.forEach((e) => e.meshes.push(supply, ret));
        for (let r = 0; r < lay.perBank; r++) {
          const x = DOOR_ZONE + r * (RACK_W + RACK_GAP) + RACK_W / 2;
          this.cylinder(g, x, (H - 0.5 + BASE_Y) / 2, z, 0.025, H - 0.5 - BASE_Y, 0x2a8fbf);
        }
      }
      this.label('hvac', g, new THREE.Vector3(runFrom + len * 0.3, H - 0.45, 0.12), 'Coolant manifold (supply / return)', true);
    } else {
      const duct = this.box(g, runFrom + len / 2, H - 0.28, W / 2, len, 0.26, 0.34, COLORS.hvac, { opacity: 0.85, m: 0.3 });
      entries.forEach((e) => e.meshes.push(duct));
      for (let r = 0; r < lay.perBank; r++) {
        const x = DOOR_ZONE + r * (RACK_W + RACK_GAP) + RACK_W / 2;
        this.box(g, x, H - 0.55, 0.9, 0.2, 0.3, 0.2, COLORS.hvac, { opacity: 0.8, noShadow: true });
        this.box(g, x, H - 0.55, W - 0.9, 0.2, 0.3, 0.2, COLORS.hvac, { opacity: 0.8, noShadow: true });
      }
    }
  }

  /** Fire suppression as recorded on the container: aerosol generators, gas cylinders + piping, or sprinklers. */
  private buildFire(o: THREE.Vector3, lay: ContainerLayout, c: BatteryContainer): Entry | null {
    const kind = (c.fire_suppression ?? '').toLowerCase();
    if (!kind) {
      return null;
    }
    const entry: Entry = { selected: this.fireSelection(c), meshes: [] };
    const g = new THREE.Group();
    g.position.copy(o);
    this.groups.fire.add(g);
    this.explodable(g, new THREE.Vector3(0, 1.4, 0));
    const { H } = lay;
    const len = lay.batteryLen - DOOR_ZONE;
    // control panel by the door + detectors on the ceiling (every kind)
    this.pickable(this.box(g, 0.2, 1.45, 0.45, 0.12, 0.5, 0.36, COLORS.fire, { flat: true }), entry);
    for (let i = 0; i < lay.perBank; i++) {
      const x = DOOR_ZONE + (i + 0.5) * (RACK_W + RACK_GAP);
      const d = new THREE.Mesh(new THREE.CylinderGeometry(0.09, 0.09, 0.05, 16), this.mat(0xf2d6d6, { m: 0.1 }));
      d.position.set(x, H - 0.08, W / 2 + (i % 2 ? 0.25 : -0.25));
      g.add(d);
    }
    if (/aerosol/.test(kind)) {
      for (let i = 0; i <= lay.perBank; i++) {
        const x = DOOR_ZONE - 0.05 + (i * len) / Math.max(lay.perBank, 1);
        this.pickable(this.box(g, x, H - 0.16, W / 2, 0.3, 0.14, 0.2, COLORS.fire, { m: 0.4, r: 0.4 }), entry);
      }
      this.label('fire', g, new THREE.Vector3(DOOR_ZONE + len / 2, H - 0.1, W / 2), `${c.fire_suppression} · ${lay.perBank + 1} generators`);
    } else if (/sprinkler|water|mist/.test(kind)) {
      this.pickable(this.cylinder(g, DOOR_ZONE + len / 2, H - 0.12, W / 2, 0.05, len + 0.6, COLORS.fire, 'z'), entry);
      for (let i = 0; i <= lay.perBank; i++) {
        const n = new THREE.Mesh(new THREE.ConeGeometry(0.06, 0.12, 10), this.mat(0xd1d5db));
        n.position.set(DOOR_ZONE + (i * len) / Math.max(lay.perBank, 1), H - 0.22, W / 2);
        n.rotation.x = Math.PI;
        g.add(n);
      }
      this.label('fire', g, new THREE.Vector3(DOOR_ZONE + len / 2, H - 0.1, W / 2), c.fire_suppression ?? 'Sprinklers');
    } else {
      // clean agent / FM-200 / Novec / inert gas / CO2: cylinders by the door, ceiling pipe and nozzles
      [0.55, 1.0].forEach((z) => {
        this.pickable(this.cylinder(g, 0.75, 0.75, z + 0.35, 0.16, 1.3, COLORS.fire), entry);
        this.cylinder(g, 0.75, 1.45, z + 0.35, 0.09, 0.16, 0x8a0f0f);
      });
      this.pickable(this.cylinder(g, DOOR_ZONE + len / 2, H - 0.12, W / 2, 0.05, len + 0.6, COLORS.fire, 'z'), entry);
      for (let i = 0; i <= lay.perBank; i++) {
        const n = new THREE.Mesh(new THREE.ConeGeometry(0.06, 0.14, 10), this.mat(COLORS.fire));
        n.position.set(DOOR_ZONE + (i * len) / Math.max(lay.perBank, 1), H - 0.22, W / 2);
        n.rotation.x = Math.PI;
        g.add(n);
      }
      this.label('fire', g, new THREE.Vector3(0.75, 1.7, 1.2), c.fire_suppression ?? 'Fire suppression');
    }
    return entry;
  }

  private paintModules(): void {
    const range = this.sohRange;
    for (const { mesh, soh } of this.moduleMeshes) {
      const mat = mesh.material as THREE.MeshStandardMaterial;
      if (this.moduleColor === 'soh' && range) {
        if (soh === null) {
          mat.color.setHex(0x55606a);
        } else {
          const t = range[1] > range[0] ? (soh - range[0]) / (range[1] - range[0]) : 1;
          mat.color.copy(SOH_LOW).lerp(SOH_HIGH, t);
        }
      } else {
        mat.color.setHex(COLORS.modules);
      }
    }
  }

  // ---------------------------------------------------------------- detail payloads

  private num(v: number | string | null | undefined, d = 2): string {
    const n = Number(v);
    return v === null || v === undefined || v === '' || !Number.isFinite(n) ? '—' : String(Number(n.toFixed(d)));
  }

  private unit(v: number | string | null | undefined, u: string, d = 2): string {
    const s = this.num(v, d);
    return s === '—' ? s : `${s} ${u}`;
  }

  /** The last dash-separated token of a code (PACK-01 -> PACK-01, CONT-S02-01-PACK-03 -> PACK-03). */
  short(code: string | null | undefined): string {
    if (!code) {
      return '—';
    }
    const m = code.match(/(PACK|MOD(?:ULE)?)-?\d+$/i);
    return m ? m[0].toUpperCase() : code;
  }

  private containerSelection(c: BatteryContainer, lay: ContainerLayout, packCount: number): Selected {
    return {
      type: 'container',
      title: c.container_number || 'Container',
      fields: [
        { label: 'Container type', value: c.container_type || '—' },
        { label: 'Drawn as', value: `${lay.sizeLabel} · ${lay.L.toFixed(2)} × ${W} × ${lay.H} m` },
        { label: 'Manufacturer', value: c.manufacturer || '—' },
        { label: 'IP rating', value: c.ip_rating || '—' },
        { label: 'Fire suppression', value: c.fire_suppression || '—' },
        { label: 'Installation date', value: c.installation_date || '—' },
        { label: 'Status', value: c.status || '—' },
        { label: 'Packs (racks)', value: String(packCount) },
        { label: 'Battery system', value: this.batterySystem?.system_name || '—' }
      ]
    };
  }

  private packSelection(p: BatteryPack, mods: BatteryModule[]): Selected {
    const soh = mods.map((m) => Number(m.soh_pct)).filter((v) => Number.isFinite(v) && v > 0);
    return {
      type: 'pack',
      title: p.pack_number || `Pack ${p.pack_id}`,
      fields: [
        { label: 'Nominal voltage', value: this.unit(p.nominal_voltage, 'V', 1) },
        { label: 'Nominal capacity', value: this.unit(p.nominal_capacity_ah, 'Ah', 0) },
        { label: 'Modules (master data)', value: `${mods.length}${p.module_count !== null && p.module_count !== mods.length ? ` (pack says ${p.module_count})` : ''}` },
        { label: 'Module SOH', value: soh.length ? `${Math.min(...soh).toFixed(2)} – ${Math.max(...soh).toFixed(2)} %` : '—' },
        { label: 'Status', value: p.status || '—' }
      ],
      link: {
        label: 'Daily Module Summary',
        route: '/analytics/daily-module-summary',
        queryParams: { pack: p.pack_id, ...(this.batterySystem ? { system: this.batterySystem.battery_system_id } : {}) }
      }
    };
  }

  private moduleSelection(m: BatteryModule, p: BatteryPack): Selected {
    return {
      type: 'module',
      title: m.serial_number || `Module ${m.module_id}`,
      fields: [
        { label: 'Pack', value: p.pack_number || '—' },
        { label: 'Chemistry', value: m.chemistry || this.batterySystem?.chemistry_code || '—' },
        { label: 'Nominal voltage', value: this.unit(m.nominal_voltage, 'V', 1) },
        { label: 'Capacity', value: this.unit(m.capacity_ah, 'Ah', 0) },
        { label: 'Cells', value: m.cell_count !== null ? String(m.cell_count) : '—' },
        { label: 'SOH', value: this.unit(m.soh_pct, '%', 2) },
        { label: 'Manufactured', value: m.manufacture_date || '—' },
        { label: 'Installed', value: m.installation_date || '—' },
        { label: 'Status', value: m.status || '—' }
      ],
      link: {
        label: 'Module telemetry',
        route: '/telemetry/module',
        queryParams: { module: m.module_id }
      }
    };
  }

  private bmsSelection(): Selected {
    const sys = this.batterySystem;
    return {
      type: 'bms',
      title: `Master BMS · ${sys?.system_name ?? ''}`.trim(),
      fields: [
        { label: 'Manufacturer', value: sys?.manufacturer || '—' },
        { label: 'Model', value: sys?.model || '—' },
        { label: 'Rated', value: sys ? `${this.num(sys.rated_power_mw)} MW / ${this.num(sys.rated_energy_mwh)} MWh` : '—' },
        { label: 'Nominal DC voltage', value: this.unit(sys?.nominal_dc_voltage, 'V', 1) },
        { label: 'Chemistry', value: sys?.chemistry_code || '—' },
        { label: 'Series cells', value: sys?.series_cells != null ? String(sys.series_cells) : '—' },
        { label: 'Parallel cells', value: sys?.parallel_cells != null ? String(sys.parallel_cells) : '—' },
        { label: 'BMS firmware', value: sys?.bms_firmware || '—' },
        { label: 'Commissioned', value: sys?.commissioned_on || '—' }
      ],
      link: sys ? { label: 'Daily Battery Summary', route: '/analytics/daily-summary', queryParams: { system: sys.battery_system_id } } : undefined
    };
  }

  private rackBmsSelection(p: BatteryPack, modules: number): Selected {
    return {
      type: 'bms',
      title: `Rack BMS · ${p.pack_number ?? p.pack_id}`,
      fields: [
        { label: 'Pack', value: p.pack_number || '—' },
        { label: 'Modules monitored', value: String(modules) },
        { label: 'Pack voltage', value: this.unit(p.nominal_voltage, 'V', 1) },
        { label: 'BMS firmware', value: this.batterySystem?.bms_firmware || '—' }
      ]
    };
  }

  private pcsSelection(p: Pcs): Selected {
    return {
      type: 'pcs',
      title: p.pcs_code,
      fields: [
        { label: 'Manufacturer / model', value: [p.manufacturer, p.model].filter(Boolean).join(' · ') || '—' },
        { label: 'Rated power', value: this.unit(p.rated_power_kw, 'kW', 0) },
        { label: 'Rated apparent power', value: this.unit(p.rated_apparent_kva, 'kVA', 0) },
        { label: 'Charge / discharge max', value: `${this.num(p.max_charge_kw, 0)} / ${this.num(p.max_discharge_kw, 0)} kW` },
        { label: 'AC', value: `${this.unit(p.rated_ac_voltage_v, 'V', 0)} · ${this.unit(p.ac_frequency_hz, 'Hz', 0)} · ${p.phases} ph` },
        { label: 'DC window', value: `${this.num(p.dc_voltage_min_v, 0)} – ${this.num(p.dc_voltage_max_v, 0)} V` },
        { label: 'Topology / cooling', value: [p.topology, p.cooling].filter(Boolean).join(' · ') || '—' },
        { label: 'Efficiency', value: this.unit(p.efficiency_pct, '%', 1) },
        { label: 'Firmware', value: p.firmware || '—' }
      ],
      link: { label: 'Daily PCS Summary', route: '/analytics/daily-pcs-summary', queryParams: { pcs: p.pcs_id } }
    };
  }

  private emsSelection(e: EmsController): Selected {
    return {
      type: 'ems',
      title: e.ems_code,
      fields: [
        { label: 'Manufacturer / model', value: [e.manufacturer, e.model].filter(Boolean).join(' · ') || '—' },
        { label: 'Firmware', value: e.firmware_version || '—' },
        { label: 'Control mode', value: e.control_mode || '—' },
        { label: 'Battery system', value: e.system_name || this.batterySystem?.system_name || '—' }
      ],
      link: {
        label: 'Daily EMS Summary',
        route: '/analytics/daily-ems-summary',
        queryParams: { ems: e.ems_id, ...(this.batterySystem ? { system: this.batterySystem.battery_system_id } : {}) }
      }
    };
  }

  private hvacSelection(h: HvacUnit): Selected {
    return {
      type: 'hvac',
      title: h.hvac_code,
      fields: [
        { label: 'Type', value: h.hvac_type || '—' },
        { label: 'Cooling capacity', value: this.unit(h.cooling_capacity_kw, 'kW', 1) },
        { label: 'Manufacturer / model', value: [h.manufacturer, h.model].filter(Boolean).join(' · ') || '—' },
        { label: 'Status', value: h.status || '—' }
      ],
      link: {
        label: 'Daily HVAC Summary',
        route: '/analytics/daily-hvac-summary',
        queryParams: { hvac: h.hvac_id, ...(this.batterySystem ? { system: this.batterySystem.battery_system_id } : {}) }
      }
    };
  }

  private fireSelection(c: BatteryContainer): Selected {
    return {
      type: 'fire',
      title: `Fire suppression · ${c.container_number ?? ''}`.trim(),
      fields: [
        { label: 'System', value: c.fire_suppression || '—' },
        { label: 'Container', value: c.container_number || '—' },
        { label: 'IP rating', value: c.ip_rating || '—' }
      ]
    };
  }

  layerOf(type: ComponentType): LayerKey {
    return TYPE_LAYER[type];
  }
}
