import { HttpErrorResponse, HttpInterceptorFn, HttpRequest } from '@angular/common/http';
import { inject } from '@angular/core';
import { catchError, from, switchMap, throwError } from 'rxjs';

import { RequestErrorService, newRequestId, requestIdOf } from '../observability/request-id';
import { AUTH_URL, PROTECTED_URLS, REVOKE_URL, TOKEN_URL } from './auth.config';
import { AuthService } from './auth.service';

/**
 * For backend and ML-service calls:
 *  - X-Request-ID: a fresh id per call; the APIs log it and echo it (response header, "request_id" in error bodies)
 *  - Authorization: Bearer <access token>; credentials (the HttpOnly refresh cookie) only on /api/auth calls
 *  - 401: refreshes the session once (single-flight rotation) and retries; if that fails -> login page
 *  - 403 / 5xx / unreachable: announced through RequestErrorService with the request id (the shell shows the banner);
 *    the error still reaches the page for its own message
 */
export const authInterceptor: HttpInterceptorFn = (req, next) => {
  const auth = inject(AuthService);
  const failures = inject(RequestErrorService);
  const isApi = PROTECTED_URLS.some((u) => req.url.startsWith(u));
  if (!isApi) {
    return next(req);
  }
  const rid = req.headers.get('X-Request-ID') || newRequestId();
  req = req.clone({ setHeaders: { 'X-Request-ID': rid } });
  if (req.url.startsWith(AUTH_URL)) {
    req = req.clone({ withCredentials: true }); // the refresh cookie is scoped to /api/auth
  }
  if (req.url.startsWith(TOKEN_URL) || req.url.startsWith(REVOKE_URL)) {
    return next(req); // no bearer token, no 401 handling on the token endpoint itself
  }
  const withToken = (r: HttpRequest<unknown>) => {
    const token = auth.accessToken();
    return token ? r.clone({ setHeaders: { Authorization: `Bearer ${token}` } }) : r;
  };
  return next(withToken(req)).pipe(
    catchError((err: unknown) => {
      if (!(err instanceof HttpErrorResponse)) {
        return throwError(() => err);
      }
      if (err.status === 401) {
        return from(auth.refresh()).pipe(
          switchMap((ok) => {
            if (!ok) {
              auth.sessionExpired();
              return throwError(() => err);
            }
            return next(withToken(req));
          })
        );
      }
      const requestId = requestIdOf(err, rid);
      if (err.status === 403) {
        failures.failures$.next({ kind: 'forbidden', status: 403, requestId,
          message: typeof err.error?.detail === 'string' ? err.error.detail : 'You do not have permission for this action.' });
      } else if (err.status >= 500) {
        failures.failures$.next({ kind: 'server', status: err.status, requestId,
          message: `The server couldn't complete the request (${err.status}).` });
      } else if (err.status === 0) {
        failures.failures$.next({ kind: 'offline', status: 0, requestId, message: 'The server is not reachable.' });
      }
      return throwError(() => err);
    })
  );
};
