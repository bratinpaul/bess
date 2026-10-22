import { CommonModule } from '@angular/common';
import { Component, OnInit, inject } from '@angular/core';
import {
  AbstractControl,
  FormArray,
  FormBuilder,
  FormGroup,
  ReactiveFormsModule,
  ValidationErrors,
  Validators
} from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';

import { INDIAN_STATES, INDIA_TIMEZONE } from '../../../core/constants/india';
import { getAllTimezones } from '../../../core/constants/timezones';
import { SiteCreateInput, SiteOwner, SiteOwnerInput, SiteUpdateInput } from '../../../core/models/site.model';
import { Tenant } from '../../../core/models/tenant.model';
import { SiteService } from '../../../core/services/site.service';
import { TenantService } from '../../../core/services/tenant.service';

function greaterThanZero(control: AbstractControl): ValidationErrors | null {
  const value = control.value;
  if (value === null || value === '' || value === undefined) {
    return null;
  }
  return Number(value) > 0 ? null : { greaterThanZero: true };
}

/** Owners must be distinct tenants, add up to at most 100%, and include at most one primary. */
function ownersValidator(control: AbstractControl): ValidationErrors | null {
  const rows = (control as FormArray).controls.map((c) => c.value as SiteOwnerInput);
  const ids = rows.map((r) => r.tenant_id).filter((id) => id !== null);
  const errors: ValidationErrors = {};
  if (new Set(ids).size !== ids.length) {
    errors['duplicateTenant'] = true;
  }
  if (rows.filter((r) => r.is_primary_owner).length > 1) {
    errors['multiplePrimary'] = true;
  }
  const total = rows.reduce((sum, r) => sum + (Number(r.ownership_pct) || 0), 0);
  if (total > 100.0001) {
    errors['over100'] = true;
  }
  return Object.keys(errors).length ? errors : null;
}

@Component({
  selector: 'app-site-form',
  standalone: true,
  imports: [CommonModule, ReactiveFormsModule, RouterLink],
  templateUrl: './site-form.component.html',
  styleUrl: './site-form.component.scss'
})
export class SiteFormComponent implements OnInit {
  private fb = inject(FormBuilder);

  siteId: number | null = null;
  isEditMode = false;
  loading = false;
  saving = false;
  error: string | null = null;

  states = INDIAN_STATES;
  timezones = getAllTimezones();
  tenants: Tenant[] = [];

  form = this.fb.group({
    site_code: ['', [Validators.required, Validators.maxLength(50)]],
    site_name: ['', [Validators.required, Validators.maxLength(200)]],
    latitude: [null as number | null],
    longitude: [null as number | null],
    address: [''],
    state: [''],
    grid_operator: [''],
    timezone: [INDIA_TIMEZONE, [Validators.required]],
    rated_power_mw: [null as number | null, [greaterThanZero]],
    rated_energy_mwh: [null as number | null, [greaterThanZero]],
    commission_date: [''],
    owners: this.fb.array<FormGroup>([], { validators: ownersValidator }),
    grid_voltage_kv: [null as number | null]
  });

  constructor(
    private route: ActivatedRoute,
    private router: Router,
    private siteService: SiteService,
    private tenantService: TenantService
  ) {}

  ngOnInit(): void {
    this.tenantService.list().subscribe({
      next: (tenants) => (this.tenants = tenants),
      error: () => {
        /* tenant is optional; the form still works without the list */
      }
    });

    const idParam = this.route.snapshot.paramMap.get('id');
    this.siteId = idParam ? Number(idParam) : null;
    this.isEditMode = !!this.siteId;

    if (this.isEditMode && this.siteId) {
      this.loading = true;
      this.siteService.get(this.siteId).subscribe({
        next: (site) => {
          this.form.patchValue({
            site_code: site.site_code,
            site_name: site.site_name,
            latitude: site.latitude,
            longitude: site.longitude,
            address: site.address ?? '',
            state: site.state ?? '',
            grid_operator: site.grid_operator ?? '',
            timezone: site.timezone,
            rated_power_mw: site.rated_power_mw,
            rated_energy_mwh: site.rated_energy_mwh,
            commission_date: site.commission_date ?? '',
            grid_voltage_kv: site.grid_voltage_kv
          });
          site.owners.forEach((o) => this.addOwner(o));
          this.form.get('timezone')?.disable();
          this.loading = false;
        },
        error: () => {
          this.error = 'Could not load site.';
          this.loading = false;
        }
      });
    }
  }

  // ---------------------------------------------------------------- owners (tenant_site)

  get owners(): FormArray<FormGroup> {
    return this.form.controls.owners;
  }

  get ownershipTotal(): number {
    return this.owners.controls.reduce((sum, c) => sum + (Number(c.value.ownership_pct) || 0), 0);
  }

  /** Tenants still available for a row: not already chosen in another row. */
  tenantOptions(rowIndex: number): Tenant[] {
    const taken = new Set(
      this.owners.controls.filter((_, i) => i !== rowIndex).map((c) => c.value.tenant_id as number | null)
    );
    return this.tenants.filter((t) => !taken.has(t.tenant_id));
  }

  addOwner(owner?: SiteOwner): void {
    const first = this.owners.length === 0;
    this.owners.push(
      this.fb.group({
        tenant_id: [owner?.tenant_id ?? (null as number | null), [Validators.required]],
        ownership_pct: [
          owner?.ownership_pct ?? (first ? 100 : null),
          [Validators.min(0.01), Validators.max(100)]
        ],
        // the first owner added becomes primary by default
        is_primary_owner: [owner?.is_primary_owner ?? first]
      })
    );
  }

  removeOwner(index: number): void {
    const wasPrimary = this.owners.at(index).value.is_primary_owner;
    this.owners.removeAt(index);
    if (wasPrimary && this.owners.length) {
      this.owners.at(0).patchValue({ is_primary_owner: true });
    }
  }

  /** Radio-like: marking one owner primary clears the rest. */
  setPrimary(index: number): void {
    this.owners.controls.forEach((c, i) => c.patchValue({ is_primary_owner: i === index }));
    this.owners.markAsDirty();
  }

  private ownerPayload(): SiteOwnerInput[] {
    return this.owners.controls.map((c) => ({
      tenant_id: Number(c.value.tenant_id),
      ownership_pct:
        c.value.ownership_pct === null || c.value.ownership_pct === '' ? null : Number(c.value.ownership_pct),
      is_primary_owner: !!c.value.is_primary_owner
    }));
  }

  submit(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }

    const raw = this.form.getRawValue();
    const basePayload: SiteUpdateInput = {
      site_code: raw.site_code!,
      site_name: raw.site_name!,
      latitude: raw.latitude,
      longitude: raw.longitude,
      address: raw.address || null,
      state: raw.state || null,
      grid_operator: raw.grid_operator || null,
      rated_power_mw: raw.rated_power_mw,
      rated_energy_mwh: raw.rated_energy_mwh,
      commission_date: raw.commission_date || null,
      owners: this.ownerPayload(),
      grid_voltage_kv: raw.grid_voltage_kv
    };

    this.saving = true;
    this.error = null;

    const request$ =
      this.isEditMode && this.siteId
        ? this.siteService.update(this.siteId, basePayload)
        : this.siteService.create({
            ...basePayload,
            owners: this.ownerPayload(),
            timezone: raw.timezone || 'UTC'
          } as SiteCreateInput);

    request$.subscribe({
      next: (site) => {
        this.saving = false;
        this.router.navigate(['/sites', site.site_id]);
      },
      error: (err) => {
        this.saving = false;
        const detail = err?.error?.detail;
        this.error =
          err?.status === 409
            ? 'Site code already exists.'
            : typeof detail === 'string'
              ? detail
              : Array.isArray(detail)
                ? detail.map((d: { msg: string }) => d.msg.replace(/^Value error, /, '')).join('; ')
                : 'Failed to save site.';
      }
    });
  }
}
