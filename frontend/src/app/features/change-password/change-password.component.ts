import { CommonModule } from '@angular/common';
import { Component, OnInit, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';

import { AuthService } from '../../core/auth/auth.service';

/** Change password (outside the shell). Mandatory after the first sign-in with the default password: until it is done the
 *  APIs answer 403 everywhere except /api/auth. On success the server ends every other session of the user. */
@Component({
  selector: 'app-change-password',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './change-password.component.html',
  styleUrl: '../login/login.component.scss'
})
export class ChangePasswordComponent implements OnInit {
  readonly auth = inject(AuthService);
  private router = inject(Router);
  private route = inject(ActivatedRoute);

  current = '';
  next = '';
  confirm = '';
  show = false;
  busy = false;
  error: string | null = null;
  rules: string[] = [];
  minLength = 10;
  private returnUrl = '/';

  async ngOnInit(): Promise<void> {
    this.returnUrl = this.route.snapshot.queryParamMap.get('returnUrl') || '/';
    try {
      const p = await this.auth.passwordPolicy();
      this.rules = p.rules;
      this.minLength = p.min_length;
    } catch {
      this.rules = [];
    }
  }

  get forced(): boolean {
    return !!this.auth.user()?.mustChangePassword;
  }

  get mismatch(): boolean {
    return !!this.confirm && this.next !== this.confirm;
  }

  get canSubmit(): boolean {
    return !!this.current && this.next.length >= this.minLength && this.next === this.confirm && !this.busy;
  }

  async submit(): Promise<void> {
    if (!this.canSubmit) {
      return;
    }
    this.busy = true;
    this.error = null;
    try {
      await this.auth.changePassword(this.current, this.next);
      void this.router.navigateByUrl(this.returnUrl.startsWith('/change-password') ? '/' : this.returnUrl);
    } catch (err: unknown) {
      const e = err as { status?: number; error?: { error_description?: string; detail?: string } };
      this.error = e?.error?.error_description || e?.error?.detail || 'Could not change the password.';
    } finally {
      this.busy = false;
    }
  }

  cancel(): void {
    if (this.forced) {
      void this.auth.logout();
    } else {
      void this.router.navigateByUrl(this.returnUrl);
    }
  }
}
