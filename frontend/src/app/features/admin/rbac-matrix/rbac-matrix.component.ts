import { CommonModule } from '@angular/common';
import { Component, OnInit, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute } from '@angular/router';

import { AuthService } from '../../../core/auth/auth.service';
import { AdminPrivilege, AdminRole, RbacChange, TokenPreview, UserAdminService, apiError } from '../../../core/services/user-admin.service';

interface Group {
  label: string;
  privileges: AdminPrivilege[];
}

/** Administration -> RBAC Matrix: roles x privileges. Edits are staged and saved as one change; affected users' tokens
 *  refresh within a minute. Tabs: matrix, token preview, change history. */
@Component({
  selector: 'app-rbac-matrix',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './rbac-matrix.component.html',
  styleUrls: ['../user-admin.scss', './rbac-matrix.component.scss']
})
export class RbacMatrixComponent implements OnInit {
  private api = inject(UserAdminService);
  private route = inject(ActivatedRoute);
  readonly auth = inject(AuthService);

  tab: 'matrix' | 'preview' | 'history' = 'matrix';
  roles: AdminRole[] = [];
  groups: Group[] = [];
  private grants = new Map<string, Set<string>>();
  private locked = new Set<string>();
  added = new Set<string>();
  removed = new Set<string>();
  filter = '';
  focusRole = '';
  busy = false;
  error: string | null = null;
  flash: string | null = null;

  previewRole = '';
  preview: TokenPreview | null = null;
  changes: RbacChange[] = [];
  changesTotal = 0;
  changeEntity = '';

  get canWrite(): boolean {
    return this.auth.hasPermission('admin:write');
  }

  get canAudit(): boolean {
    return this.auth.hasPermission('audit:read');
  }

  ngOnInit(): void {
    this.focusRole = this.route.snapshot.queryParamMap.get('role') || '';
    this.load();
  }

  load(): void {
    this.api.matrix().subscribe({
      next: (m) => this.apply(m.roles, m.privileges, m.grants, m.locked),
      error: (e) => (this.error = apiError(e, 'Could not load the RBAC matrix.'))
    });
  }

  private apply(roles: AdminRole[], privileges: AdminPrivilege[], grants: Record<string, string[]>, locked: [string, string][]): void {
    this.roles = roles;
    this.grants = new Map(roles.map((r) => [r.role_code, new Set(grants[r.role_code] || [])]));
    this.locked = new Set(locked.map(([r, c]) => `${r}|${c}`));
    this.added.clear();
    this.removed.clear();
    const byLabel = new Map<string, AdminPrivilege[]>();
    for (const p of privileges) {
      const label = p.module_label || (p.source === 'custom' ? 'Custom privileges' : p.resource);
      byLabel.set(label, [...(byLabel.get(label) || []), p]);
    }
    this.groups = [...byLabel.entries()].map(([label, ps]) => ({ label, privileges: ps })).sort((a, b) => a.label.localeCompare(b.label));
    if (!this.previewRole && roles.length) this.previewRole = this.focusRole || roles[0].role_code;
  }

  shownGroups(): Group[] {
    const q = this.filter.trim().toLowerCase();
    if (!q) return this.groups;
    return this.groups
      .map((g) => ({ label: g.label, privileges: g.privileges.filter((p) => p.code.includes(q) || g.label.toLowerCase().includes(q)) }))
      .filter((g) => g.privileges.length);
  }

  key(role: string, code: string): string {
    return `${role}|${code}`;
  }

  /** Effective state including staged edits. */
  has(role: string, code: string): boolean {
    const k = this.key(role, code);
    if (this.added.has(k)) return true;
    if (this.removed.has(k)) return false;
    return this.grants.get(role)?.has(code) ?? false;
  }

  isLocked(role: string, code: string): boolean {
    return this.locked.has(this.key(role, code));
  }

  isPending(role: string, code: string): boolean {
    const k = this.key(role, code);
    return this.added.has(k) || this.removed.has(k);
  }

  toggle(role: string, code: string): void {
    if (!this.canWrite || this.isLocked(role, code)) return;
    const k = this.key(role, code);
    const original = this.grants.get(role)?.has(code) ?? false;
    const target = !this.has(role, code);
    this.added.delete(k);
    this.removed.delete(k);
    if (target !== original) (target ? this.added : this.removed).add(k);
  }

  setRow(p: AdminPrivilege, on: boolean): void {
    for (const r of this.roles) if (this.has(r.role_code, p.code) !== on) this.toggle(r.role_code, p.code);
  }

  setColumn(role: string, on: boolean): void {
    for (const g of this.shownGroups()) for (const p of g.privileges) if (this.has(role, p.code) !== on) this.toggle(role, p.code);
  }

  get pendingCount(): number {
    return this.added.size + this.removed.size;
  }

  pendingList(set: Set<string>): string[] {
    return [...set].map((k) => k.replace('|', ' → ')).sort();
  }

  discard(): void {
    this.added.clear();
    this.removed.clear();
  }

  save(): void {
    const split = (s: Set<string>) => [...s].map((k) => k.split('|') as [string, string]);
    this.busy = true;
    this.error = this.flash = null;
    this.api.saveMatrix(split(this.added), split(this.removed)).subscribe({
      next: (r) => {
        this.busy = false;
        this.apply(r.roles, r.privileges, r.grants, r.locked);
        this.flash = r.changed_roles.length
          ? `Saved. Changed roles: ${r.changed_roles.join(', ')} - ${r.affected_users} user(s) get the new permissions within a minute.`
          : 'Nothing changed.';
        if (this.preview) this.loadPreview();
      },
      error: (e) => { this.busy = false; this.error = apiError(e, 'Could not save the matrix.'); }
    });
  }

  holders(code: string): number {
    return this.roles.filter((r) => this.has(r.role_code, code)).length;
  }

  loadPreview(): void {
    if (!this.previewRole) return;
    this.api.tokenPreview(this.previewRole).subscribe({ next: (p) => (this.preview = p), error: (e) => (this.error = apiError(e, 'Could not load the preview.')) });
  }

  previewClaims(p: TokenPreview): string {
    return JSON.stringify({ role: p.role, role_name: p.role_name, rv: p.rv, tenant_id: p.tenant_scoped ? '<user tenant>' : null, perms: p.perms }, null, 2);
  }

  loadChanges(): void {
    this.api.changes({ entity: this.changeEntity || undefined, limit: 200 }).subscribe({
      next: (r) => { this.changes = r.items; this.changesTotal = r.total; },
      error: (e) => (this.error = apiError(e, 'Could not load the history.'))
    });
  }

  show(tab: 'matrix' | 'preview' | 'history'): void {
    this.tab = tab;
    if (tab === 'preview') this.loadPreview();
    if (tab === 'history') this.loadChanges();
  }

  diff(c: RbacChange): string {
    const parts: string[] = [];
    const add = (label: string, v: unknown) => {
      if (Array.isArray(v) && v.length) parts.push(`${label}: ${v.join(', ')}`);
    };
    add('granted', c.after?.['granted']);
    add('revoked', c.before?.['revoked']);
    if (!parts.length) {
      if (c.before) parts.push('before ' + JSON.stringify(c.before));
      if (c.after) parts.push('after ' + JSON.stringify(c.after));
    }
    return parts.join(' · ');
  }
}
