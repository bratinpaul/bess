import { CommonModule } from '@angular/common';
import { Component, OnInit, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';

import { AuthService } from '../../core/auth/auth.service';

/** Sign-in page (outside the shell): e-mail + password -> OAuth2 password grant against the backend's token endpoint. */
@Component({
  selector: 'app-login',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  templateUrl: './login.component.html',
  styleUrl: './login.component.scss'
})
export class LoginComponent implements OnInit {
  private auth = inject(AuthService);
  private router = inject(Router);
  private route = inject(ActivatedRoute);

  email = '';
  password = '';
  showPassword = false;
  busy = false;
  error: string | null = null;
  info: string | null = null;
  private returnUrl = '/';

  async ngOnInit(): Promise<void> {
    const q = this.route.snapshot.queryParamMap;
    this.returnUrl = q.get('returnUrl') || '/';
    if (q.get('expired')) {
      this.info = 'Your session has ended - please sign in again.';
    }
    if (await this.auth.ensureSession()) {
      void this.router.navigateByUrl(this.returnUrl);
    }
  }

  async submit(): Promise<void> {
    if (!this.email.trim() || !this.password || this.busy) {
      return;
    }
    this.busy = true;
    this.error = null;
    try {
      await this.auth.login(this.email, this.password);
      void this.router.navigateByUrl(this.returnUrl.startsWith('/login') ? '/' : this.returnUrl);
    } catch (err: unknown) {
      const e = err as { status?: number; error?: { error_description?: string } };
      this.error = e?.status === 0 ? 'Cannot reach the server (port 8000).' : e?.error?.error_description || 'Sign-in failed.';
      this.password = '';
    } finally {
      this.busy = false;
    }
  }
}
