import { CommonModule } from '@angular/common';
import { Component, OnInit, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';

import { AccessRequestService } from '../../core/services/access-request.service';

/** Public sign-up: name, e-mail, organisation, why access is needed and a password. An Admin approves the request and
 *  assigns a role; until then the account can't sign in. */
@Component({
  selector: 'app-signup',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  templateUrl: './signup.component.html',
  styleUrls: ['../login/login.component.scss', './signup.component.scss']
})
export class SignupComponent implements OnInit {
  private service = inject(AccessRequestService);

  form = { full_name: '', email: '', organisation: '', reason: '', password: '', confirm: '' };
  show = false;
  busy = false;
  error: string | null = null;
  done: string | null = null;
  rules: string[] = [];
  minLength = 10;

  ngOnInit(): void {
    this.service.passwordPolicy().subscribe({
      next: (p) => {
        this.rules = p.rules.filter((r) => !r.toLowerCase().startsWith('must differ'));
        this.minLength = p.min_length;
      }
    });
  }

  get emailValid(): boolean {
    return /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(this.form.email.trim());
  }

  get mismatch(): boolean {
    return !!this.form.confirm && this.form.password !== this.form.confirm;
  }

  get canSubmit(): boolean {
    const f = this.form;
    return f.full_name.trim().length >= 2 && this.emailValid && f.reason.trim().length >= 10 &&
      f.password.length >= this.minLength && f.password === f.confirm && !this.busy;
  }

  submit(): void {
    if (!this.canSubmit) {
      return;
    }
    this.busy = true;
    this.error = null;
    const f = this.form;
    this.service.signup({ full_name: f.full_name.trim(), email: f.email.trim(), organisation: f.organisation.trim() || null,
      reason: f.reason.trim(), password: f.password }).subscribe({
      next: (r) => {
        this.busy = false;
        this.done = r.message;
      },
      error: (err) => {
        this.busy = false;
        const d = err?.error?.detail;
        this.error = typeof d === 'string' ? d : Array.isArray(d) ? d.map((x: { msg: string }) => x.msg.replace(/^Value error, /, '')).join('; ')
          : err?.status === 0 ? 'Cannot reach the server (port 8000).' : 'The request could not be sent.';
      }
    });
  }
}
