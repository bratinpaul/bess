import { AfterViewInit, Directive, ElementRef, NgZone, OnDestroy, effect, inject } from '@angular/core';
import { NavigationEnd, Router } from '@angular/router';
import { Subscription, filter } from 'rxjs';

import { AuthService } from './auth.service';
import { readPermissionFor, resourceFor } from './route-permissions';

const HIDDEN = 'data-rbac-hidden';

function show(el: Element, visible: boolean): void {
  const h = el as HTMLElement;
  if (visible && h.hasAttribute(HIDDEN)) {
    h.style.removeProperty('display');
    h.removeAttribute(HIDDEN);
  } else if (!visible && !h.hasAttribute(HIDDEN)) {
    h.style.setProperty('display', 'none', 'important');
    h.setAttribute(HIDDEN, '');
  }
}

/**
 * Left-nav filter: hides links to pages the role can't read (route-permissions.ts), then sections and groups left with no
 * visible link. Re-evaluated whenever the signed-in user changes.
 */
@Directive({ selector: '[rbacNav]', standalone: true })
export class RbacNavDirective implements AfterViewInit {
  private host = inject(ElementRef<HTMLElement>);
  private auth = inject(AuthService);
  private viewReady = false;

  constructor() {
    effect(() => {
      this.auth.user();
      if (this.viewReady) {
        queueMicrotask(() => this.apply());
      }
    });
  }

  ngAfterViewInit(): void {
    this.viewReady = true;
    this.apply();
  }

  private apply(): void {
    const nav = this.host.nativeElement as HTMLElement;
    nav.querySelectorAll<HTMLAnchorElement>('a.nav-link[href]').forEach((a) => {
      const perm = readPermissionFor(a.getAttribute('href') || '/');
      show(a.closest('li') ?? a, !perm || this.auth.hasPermission(perm));
    });
    // sub-sections (Core > Asset, Insights > Forecasting ...) and groups with no visible link left
    nav.querySelectorAll<HTMLElement>('li.nav-subgroup').forEach((li) => {
      const links = li.querySelectorAll('a.nav-link[href]');
      if (links.length) {
        show(li, Array.from(links).some((a) => !a.closest(`[${HIDDEN}]`)));
      }
    });
    nav.querySelectorAll<HTMLElement>('button.nav-group-label').forEach((btn) => {
      const list = btn.nextElementSibling as HTMLElement | null;
      if (!list || !list.classList.contains('nav-group')) {
        return;
      }
      const links = list.querySelectorAll('a.nav-link[href]');
      if (links.length) {
        const any = Array.from(links).some((a) => !a.closest(`[${HIDDEN}]`));
        show(btn, any);
        show(list, any);
      }
    });
  }
}

/**
 * In-page actions: on every page inside the shell, hides the write / delete controls the role may not use, judged by the
 * page's resource (route-permissions.ts):
 *   write   upload cards (.telemetry-upload-card), links to /new and /edit, Edit buttons, [data-perm="write"]
 *   delete  Delete buttons, [data-perm="delete"]
 *   exact   [data-perm="<resource:action>"] (batch:execute, kpi:execute, ml.model:approve ...)
 * Pages render lazily, so a MutationObserver re-applies the rules as content appears. UX only - the APIs enforce the same.
 */
@Directive({ selector: '[rbacActions]', standalone: true })
export class RbacActionsDirective implements AfterViewInit, OnDestroy {
  private host = inject(ElementRef<HTMLElement>);
  private auth = inject(AuthService);
  private router = inject(Router);
  private zone = inject(NgZone);
  private observer: MutationObserver | null = null;
  private sub: Subscription | null = null;
  private pending = false;

  constructor() {
    effect(() => {
      this.auth.user();
      this.schedule();
    });
  }

  ngAfterViewInit(): void {
    this.zone.runOutsideAngular(() => {
      this.observer = new MutationObserver(() => this.schedule());
      this.observer.observe(this.host.nativeElement, { childList: true, subtree: true });
    });
    this.sub = this.router.events.pipe(filter((e) => e instanceof NavigationEnd)).subscribe(() => this.schedule());
    this.schedule();
  }

  ngOnDestroy(): void {
    this.observer?.disconnect();
    this.sub?.unsubscribe();
  }

  private schedule(): void {
    if (this.pending) {
      return;
    }
    this.pending = true;
    requestAnimationFrame(() => {
      this.pending = false;
      this.apply();
    });
  }

  private apply(): void {
    const root = this.host.nativeElement as HTMLElement;
    const resource = resourceFor(this.router.url);
    const can = (action: string) => !resource || this.auth.hasPermission(`${resource}:${action}`);
    const write = can('write');
    const del = can('delete');
    root.querySelectorAll('.telemetry-upload-card, a[href$="/new"], a[href$="/edit"], button[title="Edit"], [data-perm="write"]')
      .forEach((el) => show(el.matches('input') ? el.closest('label') ?? el : el, write));
    root.querySelectorAll('button[title="Delete"], [data-perm="delete"]').forEach((el) => show(el, del));
    root.querySelectorAll<HTMLElement>('[data-perm*=":"]').forEach((el) => {
      const target = el.matches('input') ? el.closest('label') ?? el : el;
      show(target, this.auth.hasPermission(el.getAttribute('data-perm') || ''));
    });
  }
}
