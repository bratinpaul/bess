import { AuthConfig } from 'angular-oauth2-oidc';

/** Backend (issues tokens) and ML service base URLs - the interceptor attaches the bearer token only to these. */
export const BACKEND_URL = 'http://localhost:8000';
export const ML_URL = 'http://localhost:8100';
export const PROTECTED_URLS = [BACKEND_URL, ML_URL, 'http://127.0.0.1:8000', 'http://127.0.0.1:8100'];
export const AUTH_URL = `${BACKEND_URL}/api/auth`;
export const TOKEN_URL = `${AUTH_URL}/token`;
export const REVOKE_URL = `${AUTH_URL}/revoke`;

/**
 * angular-oauth2-oidc against the platform's own token endpoint (FastAPI, fastapi-users): OAuth2 password grant for login
 * and refresh_token grant for rotation. The refresh token travels only as an HttpOnly cookie (client_id bess-web), the
 * access token is kept in memory. There is no OIDC discovery / id_token (oidc: false); the RS256 access token is
 * verified by the APIs. Swapping to Keycloak later means switching to the code flow with an issuer URL.
 */
export const authConfig: AuthConfig = {
  tokenEndpoint: TOKEN_URL,
  revocationEndpoint: REVOKE_URL,
  clientId: 'bess-web',
  scope: 'bess',
  oidc: false,
  requireHttps: false, // local install over http; set true behind TLS
  responseType: 'code',
  useSilentRefresh: false,
  showDebugInformation: false
};
