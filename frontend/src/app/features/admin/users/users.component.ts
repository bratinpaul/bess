import { CommonModule } from '@angular/common';
import { Component, OnInit, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { AuthService } from '../../../core/auth/auth.service';
import { AdminRole, AdminUser, UserAdminService, apiError } from '../../../core/services/user-admin.service';

interface UserForm {
  id: string | null;
  email: string;
  full_name: string;
  role_code: string;
  tenant_id: number | null;
  is_active: boolean;
}

/** Administration -> Users: create accounts, change role / tenant / status, unlock, reset password. */
@Component({
  selector: 'app-admin-users',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './users.component.html',
  styleUrl: '../user-admin.scss'
})
export class UsersComponent implements OnInit {
  private api = inject(UserAdminService);
  private auth = inject(AuthService);

  users: AdminUser[] = [];
  roles: AdminRole[] = [];
  tenants: { tenant_id: number; name: string }[] = [];
  q = '';
  roleFilter = '';
  statusFilter = '';
  form: UserForm | null = null;
  busy = false;
  error: string | null = null;
  flash: string | null = null;
  secret: { email: string; password: string } | null = null;

  ngOnInit(): void {
    this.api.roles().subscribe({ next: (r) => (this.roles = r) });
    this.api.tenants().subscribe({ next: (t) => (this.tenants = t) });
    this.load();
  }

  load(): void {
    this.api.users().subscribe({
      next: (u) => (this.users = u),
      error: (e) => (this.error = apiError(e, 'Could not load the users.'))
    });
  }

  get assignableRoles(): AdminRole[] {
    return this.roles.filter((r) => r.role_code !== 'BATCH_SERVICE' || this.form?.id);
  }

  get shown(): AdminUser[] {
    const q = this.q.trim().toLowerCase();
    return this.users.filter((u) =>
      (!q || u.email.includes(q) || (u.full_name || '').toLowerCase().includes(q)) &&
      (!this.roleFilter || u.role_code === this.roleFilter) &&
      (!this.statusFilter ||
        (this.statusFilter === 'active' && u.is_active && !u.locked) ||
        (this.statusFilter === 'disabled' && !u.is_active) ||
        (this.statusFilter === 'locked' && u.locked) ||
        (this.statusFilter === 'service' && u.is_service_account)));
  }

  isSelf(u: AdminUser): boolean {
    return u.email === this.auth.user()?.email;
  }

  tenantScoped(code: string): boolean {
    return !!this.roles.find((r) => r.role_code === code)?.is_tenant_scoped;
  }

  newUser(): void {
    this.form = { id: null, email: '', full_name: '', role_code: '', tenant_id: null, is_active: true };
    this.secret = null;
  }

  edit(u: AdminUser): void {
    this.form = { id: u.id, email: u.email, full_name: u.full_name || '', role_code: u.role_code, tenant_id: u.tenant_id, is_active: u.is_active };
    this.secret = null;
  }

  save(): void {
    const f = this.form;
    if (!f) return;
    this.busy = true;
    this.error = this.flash = null;
    const tenant = this.tenantScoped(f.role_code) ? f.tenant_id : null;
    const done = () => (this.busy = false);
    if (!f.id) {
      this.api.addUser({ email: f.email, full_name: f.full_name, role_code: f.role_code, tenant_id: tenant }).subscribe({
        next: (r) => {
          done();
          this.form = null;
          this.secret = { email: r.user.email, password: r.temporary_password };
          this.load();
        },
        error: (e) => { done(); this.error = apiError(e, 'Could not create the user.'); }
      });
    } else {
      this.api.editUser(f.id, { full_name: f.full_name, role_code: f.role_code, tenant_id: tenant, is_active: f.is_active }).subscribe({
        next: (u) => { done(); this.form = null; this.flash = `${u.email} updated.`; this.load(); },
        error: (e) => { done(); this.error = apiError(e, 'Could not update the user.'); }
      });
    }
  }

  toggleActive(u: AdminUser): void {
    this.error = this.flash = null;
    this.api.editUser(u.id, { is_active: !u.is_active }).subscribe({
      next: (r) => { this.flash = `${r.email} ${r.is_active ? 'enabled' : 'disabled and signed out'}.`; this.load(); },
      error: (e) => (this.error = apiError(e, 'Could not change the account.'))
    });
  }

  unlock(u: AdminUser): void {
    this.error = this.flash = null;
    this.api.unlockUser(u.id).subscribe({
      next: (r) => { this.flash = `${r.email} unlocked.`; this.load(); },
      error: (e) => (this.error = apiError(e, 'Could not unlock the account.'))
    });
  }

  reset(u: AdminUser): void {
    this.error = this.flash = null;
    this.api.resetPassword(u.id).subscribe({
      next: (r) => { this.secret = { email: r.user.email, password: r.temporary_password }; this.load(); },
      error: (e) => (this.error = apiError(e, 'Could not reset the password.'))
    });
  }
}
