import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';

import { AuthService } from './auth.service';
import { permissionFor } from './route-permissions';

/** Every page inside the shell needs a session (renewed from the refresh cookie after a reload) and a non-default password. */
export const authGuard: CanActivateFn = async (_route, state) => {
  const auth = inject(AuthService);
  const router = inject(Router);
  if (!(await auth.ensureSession())) {
    return router.createUrlTree(['/login'], { queryParams: { returnUrl: state.url } });
  }
  if (auth.user()?.mustChangePassword) {
    // the APIs refuse a must-change-password token everywhere except /api/auth
    return router.createUrlTree(['/change-password'], { queryParams: { returnUrl: state.url } });
  }
  return true;
};

/** Route-level permission check: `canActivate: [permissionGuard], data: { permission: 'master.asset:write' }`. */
export const permissionGuard: CanActivateFn = (route) => {
  const auth = inject(AuthService);
  const router = inject(Router);
  const needed = route.data?.['permission'] as string | string[] | undefined;
  if (!needed || auth.hasPermission(needed)) {
    return true;
  }
  auth.forbidden$.next(`Your role (${auth.user()?.roleName ?? 'none'}) cannot open this page.`);
  return router.createUrlTree(['/']);
};

/** The change-password page needs a session (but not a changed password). */
export const sessionGuard: CanActivateFn = async (_route, state) => {
  const auth = inject(AuthService);
  const router = inject(Router);
  return (await auth.ensureSession()) ? true : router.createUrlTree(['/login'], { queryParams: { returnUrl: state.url } });
};

/** Every page inside the shell: the role needs the page's permission (route-permissions.ts) - typing a URL is blocked too. */
export const routeAccessGuard: CanActivateFn = (_route, state) => {
  const auth = inject(AuthService);
  const router = inject(Router);
  const needed = permissionFor(state.url);
  if (!needed || auth.hasPermission(needed)) {
    return true;
  }
  auth.forbidden$.next(`Your role (${auth.user()?.roleName ?? 'none'}) cannot open this page.`);
  return router.createUrlTree(['/dashboard/map-view']);
};
