import { Directive, TemplateRef, ViewContainerRef, effect, inject, input } from '@angular/core';

import { AuthService } from './auth.service';

/**
 * Renders its element only when the signed-in user holds the permission(s):
 *   <button *hasPermission="'master.asset:write'">Edit</button>
 *   <a *hasPermission="['ml.run:execute']">Train</a>
 * UX only - the APIs enforce the same RBAC matrix.
 */
@Directive({ selector: '[hasPermission]', standalone: true })
export class HasPermissionDirective {
  private tpl = inject(TemplateRef<unknown>);
  private vcr = inject(ViewContainerRef);
  private auth = inject(AuthService);
  readonly hasPermission = input.required<string | string[]>();
  private shown = false;

  constructor() {
    effect(() => {
      this.auth.user(); // re-evaluate on login / role change
      const ok = this.auth.hasPermission(this.hasPermission());
      if (ok && !this.shown) {
        this.vcr.createEmbeddedView(this.tpl);
        this.shown = true;
      } else if (!ok && this.shown) {
        this.vcr.clear();
        this.shown = false;
      }
    });
  }
}
