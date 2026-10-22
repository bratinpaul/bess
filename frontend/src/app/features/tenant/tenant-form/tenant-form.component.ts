import { CommonModule } from '@angular/common';
import { Component, OnInit, inject } from '@angular/core';
import { AbstractControl, FormArray, FormBuilder, FormGroup, ReactiveFormsModule, ValidationErrors, Validators } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';

import {
  TENANT_STATUSES,
  TENANT_TYPE_LABELS,
  TenantContact,
  TenantFormContact,
  TenantInput,
  TenantStatus
} from '../../../core/models/tenant.model';
import { TenantService } from '../../../core/services/tenant.service';

// same rules as the API (backend/app/schemas/tenant.py)
const EMAIL_PATTERN = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
const PHONE_PATTERN = /^[0-9+()\-.\s]{5,30}$/;

const text = (v: string | null | undefined) => (v && v.trim() ? v.trim() : null);

/** The primary contact section is optional, but once anything is typed into it a name is needed. */
function nameIfAnyFilled(group: AbstractControl): ValidationErrors | null {
  const v = group.value;
  const anyFilled = [v.role, v.phone, v.email].some((x) => !!text(x));
  return anyFilled && !text(v.contact_name) ? { nameRequired: true } : null;
}

@Component({
  selector: 'app-tenant-form',
  standalone: true,
  imports: [CommonModule, ReactiveFormsModule, RouterLink],
  templateUrl: './tenant-form.component.html',
  styleUrl: './tenant-form.component.scss'
})
export class TenantFormComponent implements OnInit {
  private fb = inject(FormBuilder);

  tenantId: number | null = null;
  isEditMode = false;
  loading = false;
  saving = false;
  error: string | null = null;

  statuses = TENANT_STATUSES;
  types: string[] = [];
  typesError = false;

  form = this.fb.group({
    // a name of only spaces is not a name
    name: ['', [Validators.required, Validators.maxLength(200), Validators.pattern(/\S/)]],
    legal_name: ['', [Validators.maxLength(200)]],
    tenant_type: [null as string | null],
    status: ['active' as TenantStatus, [Validators.required]],
    address_line1: ['', [Validators.maxLength(200)]],
    address_line2: ['', [Validators.maxLength(200)]],
    city: ['', [Validators.maxLength(100)]],
    state_province: ['', [Validators.maxLength(100)]],
    postal_code: ['', [Validators.maxLength(20)]],
    country: ['', [Validators.maxLength(100)]],
    phone: ['', [Validators.maxLength(30), Validators.pattern(PHONE_PATTERN)]],
    email: ['', [Validators.maxLength(200), Validators.pattern(EMAIL_PATTERN)]],
    primaryContact: this.contactGroup(null, false),
    additionalContacts: this.fb.array<FormGroup>([])
  });

  constructor(
    private route: ActivatedRoute,
    private router: Router,
    private tenantService: TenantService
  ) {}

  get primaryContact(): FormGroup {
    return this.form.controls.primaryContact;
  }

  get additionalContacts(): FormArray<FormGroup> {
    return this.form.controls.additionalContacts;
  }

  ngOnInit(): void {
    const idParam = this.route.snapshot.paramMap.get('id');
    this.tenantId = idParam ? Number(idParam) : null;
    this.isEditMode = !!this.tenantId;

    this.tenantService.types().subscribe({
      next: (types) => (this.types = types),
      error: () => (this.typesError = true)
    });

    if (this.isEditMode && this.tenantId) {
      this.loading = true;
      this.tenantService.get(this.tenantId).subscribe({
        next: (t) => {
          this.form.patchValue({
            name: t.name,
            legal_name: t.legal_name ?? '',
            tenant_type: t.tenant_type,
            status: t.status,
            address_line1: t.address_line1 ?? '',
            address_line2: t.address_line2 ?? '',
            city: t.city ?? '',
            state_province: t.state_province ?? '',
            postal_code: t.postal_code ?? '',
            country: t.country ?? '',
            phone: t.phone ?? '',
            email: t.email ?? ''
          });
          const primary = t.contacts.find((c) => c.is_primary) ?? null;
          this.form.setControl('primaryContact', this.contactGroup(primary, false));
          for (const c of t.contacts.filter((c) => c !== primary)) {
            this.additionalContacts.push(this.contactGroup(c, true));
          }
          this.loading = false;
        },
        error: () => {
          this.error = 'Could not load tenant.';
          this.loading = false;
        }
      });
    }
  }

  typeLabel(type: string): string {
    return TENANT_TYPE_LABELS[type] ?? type;
  }

  // ---------------------------------------------------------------- contacts

  /** One contact's controls; the name is required only on additional contacts (the primary one is optional). */
  private contactGroup(c: TenantContact | null, nameRequired: boolean): FormGroup {
    const nameValidators = [Validators.maxLength(200)];
    if (nameRequired) {
      nameValidators.push(Validators.required, Validators.pattern(/\S/));
    }
    return this.fb.group(
      {
        contact_id: [c?.contact_id ?? null],
        contact_name: [c?.contact_name ?? '', nameValidators],
        role: [c?.role ?? '', [Validators.maxLength(50)]],
        phone: [c?.phone ?? '', [Validators.maxLength(30), Validators.pattern(PHONE_PATTERN)]],
        email: [c?.email ?? '', [Validators.maxLength(200), Validators.pattern(EMAIL_PATTERN)]]
      },
      { validators: nameRequired ? [] : [nameIfAnyFilled] }
    );
  }

  addContact(): void {
    this.additionalContacts.push(this.contactGroup(null, true));
  }

  removeContact(index: number): void {
    this.additionalContacts.removeAt(index);
  }

  /** Swap an additional contact with the primary one (an empty primary section just takes its place). */
  makePrimary(index: number): void {
    const promoted = this.additionalContacts.at(index).getRawValue();
    const current = this.primaryContact.getRawValue();
    const hadPrimary = !!text(current.contact_name);
    this.primaryContact.reset(promoted);
    if (hadPrimary) {
      const demoted = this.contactGroup(null, true);
      demoted.reset(current);
      this.additionalContacts.setControl(index, demoted);
    } else {
      this.additionalContacts.removeAt(index);
    }
    this.primaryContact.markAsDirty();
  }

  contactInvalid(group: AbstractControl, name: string): boolean {
    const c = group.get(name);
    return !!c && c.invalid && c.touched;
  }

  private contactPayload(group: AbstractControl, isPrimary: boolean): TenantFormContact {
    const v = group.getRawValue();
    return {
      contact_id: v.contact_id ?? null,
      contact_name: v.contact_name.trim(),
      role: text(v.role),
      phone: text(v.phone),
      email: text(v.email),
      is_primary: isPrimary
    };
  }

  // ---------------------------------------------------------------- save

  invalid(name: string): boolean {
    const control = this.form.get(name);
    return !!control && control.invalid && control.touched;
  }

  submit(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }
    const raw = this.form.getRawValue();
    // an empty primary section means "no primary contact"; in edit mode that deletes the one that was there
    const contacts: TenantFormContact[] = [];
    if (text(this.primaryContact.value.contact_name)) {
      contacts.push(this.contactPayload(this.primaryContact, true));
    }
    for (const row of this.additionalContacts.controls) {
      contacts.push(this.contactPayload(row, false));
    }
    const payload: TenantInput = {
      name: raw.name!.trim(),
      legal_name: text(raw.legal_name),
      tenant_type: raw.tenant_type || null,
      status: raw.status!,
      address_line1: text(raw.address_line1),
      address_line2: text(raw.address_line2),
      city: text(raw.city),
      state_province: text(raw.state_province),
      postal_code: text(raw.postal_code),
      country: text(raw.country),
      phone: text(raw.phone),
      email: text(raw.email),
      contacts
    };
    if (!payload.name) {
      this.form.get('name')?.setErrors({ required: true });
      this.form.get('name')?.markAsTouched();
      return;
    }

    this.saving = true;
    this.error = null;
    const request$ =
      this.isEditMode && this.tenantId
        ? this.tenantService.update(this.tenantId, payload)
        : this.tenantService.create(payload);

    request$.subscribe({
      next: (tenant) => {
        this.saving = false;
        this.router.navigate(['/tenants', tenant.tenant_id]);
      },
      error: (err) => {
        this.saving = false;
        const detail = err?.error?.detail;
        this.error = Array.isArray(detail)
          ? detail.map((d: { msg: string }) => d.msg.replace(/^Value error, /, '')).join('; ')
          : detail || 'Failed to save tenant.';
      }
    });
  }
}
