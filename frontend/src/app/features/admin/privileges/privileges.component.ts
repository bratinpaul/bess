import { CommonModule } from '@angular/common';
import { Component, OnInit, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { AdminPrivilege, UserAdminService, apiError } from '../../../core/services/user-admin.service';

/** Administration -> Privileges: the catalogue of permission codes; system ones come from the code that enforces them. */
@Component({
  selector: 'app-admin-privileges',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './privileges.component.html',
  styleUrl: '../user-admin.scss'
})
export class PrivilegesComponent implements OnInit {
  private api = inject(UserAdminService);

  readonly actions = ['read', 'write', 'delete', 'execute', 'approve'];
  privileges: AdminPrivilege[] = [];
  q = '';
  sourceFilter = '';
  form: { resource: string; action: string; module_label: string; description: string } | null = null;
  editing: { id: number; module_label: string; description: string } | null = null;
  busy = false;
  error: string | null = null;
  flash: string | null = null;

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    this.api.privileges().subscribe({ next: (p) => (this.privileges = p), error: (e) => (this.error = apiError(e, 'Could not load the privileges.')) });
  }

  get shown(): AdminPrivilege[] {
    const q = this.q.trim().toLowerCase();
    return this.privileges.filter((p) =>
      (!q || p.code.includes(q) || (p.module_label || '').toLowerCase().includes(q)) &&
      (!this.sourceFilter || (this.sourceFilter === 'not-enforced' ? !p.enforced : p.source === this.sourceFilter)));
  }

  get notEnforced(): number {
    return this.privileges.filter((p) => !p.enforced).length;
  }

  add(): void {
    const f = this.form;
    if (!f) return;
    this.busy = true;
    this.error = this.flash = null;
    this.api.addPrivilege({ resource: f.resource, action: f.action, module_label: f.module_label || null, description: f.description || null }).subscribe({
      next: (p) => { this.busy = false; this.form = null; this.flash = `${p.code} added - grant it in the RBAC matrix. It protects nothing until code checks it.`; this.load(); },
      error: (e) => { this.busy = false; this.error = apiError(e, 'Could not add the privilege.'); }
    });
  }

  startEdit(p: AdminPrivilege): void {
    this.editing = { id: p.privilege_id, module_label: p.module_label || '', description: p.description || '' };
  }

  saveEdit(): void {
    const e = this.editing;
    if (!e) return;
    this.api.editPrivilege(e.id, { module_label: e.module_label || null, description: e.description || null }).subscribe({
      next: (p) => { this.editing = null; this.flash = `${p.code} updated.`; this.load(); },
      error: (err) => (this.error = apiError(err, 'Could not update the privilege.'))
    });
  }

  remove(p: AdminPrivilege): void {
    this.error = this.flash = null;
    this.api.deletePrivilege(p.privilege_id).subscribe({
      next: () => { this.flash = `${p.code} deleted.`; this.load(); },
      error: (e) => (this.error = apiError(e, 'Could not delete the privilege.'))
    });
  }
}
