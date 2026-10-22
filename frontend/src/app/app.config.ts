import { ApplicationConfig, provideZoneChangeDetection } from '@angular/core';
import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { provideRouter } from '@angular/router';
import { MemoryStorage, OAuthStorage, provideOAuthClient } from 'angular-oauth2-oidc';

import { routes } from './app.routes';
import { authInterceptor } from './core/auth/auth.interceptor';

export const appConfig: ApplicationConfig = {
  providers: [
    provideZoneChangeDetection({ eventCoalescing: true }),
    provideRouter(routes),
    provideHttpClient(withInterceptors([authInterceptor])),
    // our interceptor attaches the token (and handles 401 refresh), so the library's own resource-server hook stays off
    provideOAuthClient({ resourceServer: { sendAccessToken: false } }),
    // access token in memory only (never sessionStorage / localStorage); the refresh token is an HttpOnly cookie
    { provide: OAuthStorage, useFactory: () => new MemoryStorage() }
  ]
};
