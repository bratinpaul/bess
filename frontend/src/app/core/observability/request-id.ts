import { HttpErrorResponse } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Subject } from 'rxjs';

/** A request id for one API call (sent as X-Request-ID; the APIs echo it in the response header and error bodies). */
export function newRequestId(): string {
  const c = globalThis.crypto;
  if (c && typeof c.randomUUID === 'function') {
    return c.randomUUID().replace(/-/g, '');
  }
  return Array.from({ length: 32 }, () => Math.floor(Math.random() * 16).toString(16)).join('');
}

/** The request id of a failed call: the error body's request_id, else the response header, else the id we sent. */
export function requestIdOf(err: HttpErrorResponse, sent?: string): string | null {
  const body = err.error as { request_id?: string } | null;
  return (body && typeof body === 'object' && body.request_id) || err.headers?.get('x-request-id') || sent || null;
}

export interface RequestFailure {
  kind: 'forbidden' | 'server' | 'offline';
  message: string;
  status: number;
  requestId: string | null;
}

/** Failed API calls the shell announces (403, 5xx, unreachable) - with the reference an admin can search for. */
@Injectable({ providedIn: 'root' })
export class RequestErrorService {
  readonly failures$ = new Subject<RequestFailure>();
}
