import { HttpClient } from '@angular/common/http';
import { Injectable, NgZone, computed, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { OAuthService, OAuthStorage } from 'angular-oauth2-oidc';
import { Subject, firstValueFrom } from 'rxjs';

import { AUTH_URL, REVOKE_URL, authConfig } from './auth.config';

/** The signed-in user, read from the RS256 access token's claims (the APIs verify the signature). */
export interface AuthUser {
  userId: string;
  email: string;
  name: string | null;
  role: string;
  roleName: string;
  permissions: string[];
  tenantId: number | null;
  mustChangePassword: boolean;
}

interface TokenResponse {
  access_token: string;
  expires_in: number;
}

type TabMessage =
  | { type: 'hello' }
  | { type: 'token'; accessToken: string; expiresAt: number; storedAt: number }
  | { type: 'logout' };

/** localStorage hint (not a secret) that an HttpOnly refresh cookie may exist - avoids a pointless refresh call otherwise */
const SESSION_HINT = 'bess.session';
const CHANNEL = 'bess-auth';

/**
 * Login / logout / token lifecycle on top of angular-oauth2-oidc.
 *  - The access token (15 min) lives only in memory (OAuthStorage = MemoryStorage, see app.config.ts).
 *  - The refresh token never reaches page scripts: the backend keeps it in an HttpOnly, SameSite=Strict cookie scoped to
 *    /api/auth, sent only on token / revoke calls (the interceptor sets withCredentials there).
 *  - refresh(): single flight, scheduled at 75 % of the access-token lifetime and on demand after a 401.
 *  - Tabs share one session over a BroadcastChannel: a new tab asks the others for the current access token before falling
 *    back to the cookie; refreshed tokens are pushed to every tab; signing out in one tab signs out all of them.
 */
@Injectable({ providedIn: 'root' })
export class AuthService {
  private oauth = inject(OAuthService);
  private storage = inject(OAuthStorage);
  private http = inject(HttpClient);
  private router = inject(Router);
  private zone = inject(NgZone);

  private readonly userSignal = signal<AuthUser | null>(null);
  readonly user = this.userSignal.asReadonly();
  readonly isLoggedIn = computed(() => this.userSignal() !== null);
  /** API answered 403 - the shell shows a banner */
  readonly forbidden$ = new Subject<string>();

  private refreshing: Promise<boolean> | null = null;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private channel: BroadcastChannel | null = null;
  private ready: Promise<void>;

  constructor() {
    this.oauth.configure(authConfig);
    this.openChannel();
    this.ready = this.restore();
  }

  // ------------------------------------------------------------------ session restore / tabs

  private openChannel(): void {
    if (typeof BroadcastChannel === 'undefined') {
      return;
    }
    this.channel = new BroadcastChannel(CHANNEL);
    this.channel.onmessage = (ev: MessageEvent<TabMessage>) => this.zone.run(() => this.onTabMessage(ev.data));
  }

  private onTabMessage(msg: TabMessage): void {
    if (msg.type === 'hello') {
      const token = this.accessToken();
      if (token) {
        this.post({ type: 'token', accessToken: token, expiresAt: this.oauth.getAccessTokenExpiration(), storedAt: this.storedAt() });
      }
    } else if (msg.type === 'token') {
      if (msg.expiresAt > (this.oauth.getAccessTokenExpiration() || 0)) {
        this.storeToken(msg.accessToken, msg.expiresAt, msg.storedAt);
        this.applyToken();
      }
    } else if (msg.type === 'logout') {
      this.clear();
      void this.router.navigate(['/login']);
    }
  }

  private post(msg: TabMessage): void {
    try {
      this.channel?.postMessage(msg);
    } catch {
      // channel closed - other tabs will refresh on their own
    }
  }

  /** On startup: ask another tab for the current token; otherwise renew from the refresh cookie (if a session may exist). */
  private async restore(): Promise<void> {
    if (!this.hint()) {
      return;
    }
    if (this.channel) {
      const got = new Promise<boolean>((resolve) => {
        const t = setTimeout(() => resolve(false), 300);
        const listener = (ev: MessageEvent<TabMessage>) => {
          if (ev.data?.type === 'token') {
            clearTimeout(t);
            this.channel?.removeEventListener('message', listener);
            resolve(true);
          }
        };
        this.channel!.addEventListener('message', listener);
      });
      this.post({ type: 'hello' });
      if (await got) {
        return; // onTabMessage stored and applied it
      }
    }
    await this.refresh();
  }

  /** For the route guard: true when signed in, renewing the access token from the refresh cookie if needed. */
  async ensureSession(): Promise<boolean> {
    await this.ready;
    if (this.userSignal() && this.oauth.hasValidAccessToken()) {
      return true;
    }
    return this.hint() ? this.refresh() : false;
  }

  // ------------------------------------------------------------------ login / refresh / logout

  async login(email: string, password: string): Promise<void> {
    await this.oauth.fetchTokenUsingPasswordFlow(email.trim(), password);
    this.setHint(true);
    this.applyToken();
    this.broadcastToken();
  }

  /** Single-flight refresh through the HttpOnly cookie; resolves false (and signs out locally) when it can't be renewed. */
  refresh(): Promise<boolean> {
    if (this.refreshing) {
      return this.refreshing;
    }
    const attempt = () => this.oauth.refreshToken().then(() => true);
    this.refreshing = attempt()
      .catch(async (err) => {
        // another tab rotated the cookie a moment ago - the browser now holds the successor, so try once more
        if (String(err?.error?.error_description ?? '').includes('already rotated')) {
          await new Promise((r) => setTimeout(r, 700));
          return attempt();
        }
        throw err;
      })
      .then(() => {
        this.applyToken();
        this.broadcastToken();
        return true;
      })
      .catch(() => {
        this.clear();
        return false;
      })
      .finally(() => (this.refreshing = null));
    return this.refreshing;
  }

  async logout(redirect = true): Promise<void> {
    try {
      await firstValueFrom(this.http.post(REVOKE_URL, new URLSearchParams({ client_id: 'bess-web' }).toString(), {
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' }
      }));
    } catch {
      // already revoked / offline - still clear locally
    }
    this.post({ type: 'logout' });
    this.clear();
    if (redirect) {
      void this.router.navigate(['/login']);
    }
  }

  /** Called by the interceptor when a refresh failed: back to the login page, returning here afterwards. */
  sessionExpired(): void {
    this.clear();
    void this.router.navigate(['/login'], { queryParams: { returnUrl: this.router.url, expired: 1 } });
  }

  /** Changes the password; the server ends all other sessions and returns a fresh one (must_change_password cleared). */
  async changePassword(current: string, next: string): Promise<void> {
    const res = await firstValueFrom(this.http.post<TokenResponse>(`${AUTH_URL}/change-password`, {
      current_password: current, new_password: next, client_id: 'bess-web'
    }));
    const now = Date.now();
    this.storeToken(res.access_token, now + res.expires_in * 1000, now);
    this.setHint(true);
    this.applyToken();
    this.broadcastToken();
  }

  passwordPolicy(): Promise<{ min_length: number; rules: string[] }> {
    return firstValueFrom(this.http.get<{ min_length: number; rules: string[] }>(`${AUTH_URL}/password-policy`));
  }

  accessToken(): string | null {
    return this.oauth.hasValidAccessToken() ? this.oauth.getAccessToken() : null;
  }

  hasPermission(perm: string | string[]): boolean {
    const perms = this.userSignal()?.permissions ?? [];
    return (Array.isArray(perm) ? perm : [perm]).every((p) => perms.includes(p));
  }

  // ------------------------------------------------------------------ internals

  private storeToken(accessToken: string, expiresAt: number, storedAt: number): void {
    this.storage.setItem('access_token', accessToken);
    this.storage.setItem('expires_at', String(expiresAt));
    this.storage.setItem('access_token_stored_at', String(storedAt));
  }

  private broadcastToken(): void {
    const token = this.oauth.getAccessToken();
    if (token) {
      this.post({ type: 'token', accessToken: token, expiresAt: this.oauth.getAccessTokenExpiration(), storedAt: this.storedAt() });
    }
  }

  private storedAt(): number {
    return Number(this.storage.getItem('access_token_stored_at') ?? Date.now());
  }

  private applyToken(): void {
    const token = this.oauth.getAccessToken();
    const claims = token ? decodeClaims(token) : null;
    if (!claims) {
      this.userSignal.set(null);
      return;
    }
    this.userSignal.set({
      userId: String(claims['sub']),
      email: String(claims['email'] ?? ''),
      name: (claims['name'] as string) ?? null,
      role: String(claims['role'] ?? ''),
      roleName: String(claims['role_name'] ?? ''),
      permissions: (claims['perms'] as string[]) ?? [],
      tenantId: (claims['tenant_id'] as number) ?? null,
      mustChangePassword: Boolean(claims['mcp'])
    });
    this.schedule();
  }

  private schedule(): void {
    if (this.timer) {
      clearTimeout(this.timer);
    }
    const expires = this.oauth.getAccessTokenExpiration();
    const stored = this.storedAt();
    const lifetime = Math.max(expires - stored, 60_000);
    const due = Math.max(stored + lifetime * 0.75 - Date.now(), 5_000);
    this.timer = setTimeout(() => void this.refresh(), due);
  }

  private hint(): boolean {
    try {
      return localStorage.getItem(SESSION_HINT) === '1';
    } catch {
      return true;
    }
  }

  private setHint(on: boolean): void {
    try {
      if (on) {
        localStorage.setItem(SESSION_HINT, '1');
      } else {
        localStorage.removeItem(SESSION_HINT);
      }
    } catch {
      // storage blocked - restore() will simply try the cookie
    }
  }

  private clear(): void {
    if (this.timer) {
      clearTimeout(this.timer);
      this.timer = null;
    }
    this.setHint(false);
    this.oauth.logOut(true); // noRedirectToLogoutUrl - just drop the in-memory tokens
    this.userSignal.set(null);
  }
}

function decodeClaims(token: string): Record<string, unknown> | null {
  try {
    const part = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
    const json = decodeURIComponent(
      atob(part.padEnd(part.length + ((4 - (part.length % 4)) % 4), '='))
        .split('')
        .map((c) => '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2))
        .join('')
    );
    return JSON.parse(json);
  } catch {
    return null;
  }
}
