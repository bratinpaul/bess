import { CommonModule } from '@angular/common';
import { Component, OnInit, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';

import { AdminRole, UserAdminService, apiError } from '../../../core/services/user-admin.service';

interface RoleForm {
  editing: string | null;
  role_code: string;
  role_name: string;
  description: string;
  is_tenant_scoped: boolean;
  copy_from: string;
}

/** Administration -> Roles: create, rename and delete roles; their privileges are set in the RBAC matrix. */
@Component({
  selector: 'app-admin-roles',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  templateUrl: './roles.component.html',
  styleUrl: '../user-admin.scss'
})
export class RolesComponent implements OnInit {
  private api = inject(UserAdminService);

  roles: AdminRole[] = [];
  form: RoleForm | null = null;
  busy = false;
  error: string | null = null;
  flash: string | null = null;

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    this.api.roles().subscribe({ next: (r) => (this.roles = r), error: (e) => (this.error = apiError(e, 'Could not load the roles.')) });
  }

  newRole(): void {
    this.form = { editing: null, role_code: '', role_name: '', description: '', is_tenant_scoped: false, copy_from: '' };
  }

  edit(r: AdminRole): void {
    this.form = { editing: r.role_code, role_code: r.role_code, role_name: r.role_name, description: r.description || '',
      is_tenant_scoped: r.is_tenant_scoped, copy_from: '' };
  }

  save(): void {
    const f = this.form;
    if (!f) return;
    this.busy = true;
    this.error = this.flash = null;
    const req = f.editing
      ? this.api.editRole(f.editing, { role_name: f.role_name, description: f.description || null, is_tenant_scoped: f.is_tenant_scoped })
      : this.api.addRole({ role_code: f.role_code, role_name: f.role_name, description: f.description || null,
          is_tenant_scoped: f.is_tenant_scoped, copy_from: f.copy_from || null });
    req.subscribe({
      next: (r) => { this.busy = false; this.form = null; this.flash = `Role ${r.role_code} saved.`; this.load(); },
      error: (e) => { this.busy = false; this.error = apiError(e, 'Could not save the role.'); }
    });
  }

  remove(r: AdminRole): void {
    this.error = this.flash = null;
    this.api.deleteRole(r.role_code).subscribe({
      next: () => { this.flash = `Role ${r.role_code} deleted.`; this.load(); },
      error: (e) => (this.error = apiError(e, 'Could not delete the role.'))
    });
  }
}
