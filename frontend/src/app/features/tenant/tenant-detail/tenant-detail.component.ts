import { CommonModule } from '@angular/common';
import { Component, OnInit, inject } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';

import { TenantContact, TenantContactInput, TenantDetail } from '../../../core/models/tenant.model';
import { TenantService } from '../../../core/services/tenant.service';

// same rules as the API (backend/app/schemas/tenant.py)
const EMAIL_PATTERN = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
const PHONE_PATTERN = /^[0-9+()\-.\s]{5,30}$/;

@Component({
  selector: 'app-tenant-detail',
  standalone: true,
  imports: [CommonModule, RouterLink, ReactiveFormsModule],
  templateUrl: './tenant-detail.component.html',
  styleUrl: './tenant-detail.component.scss'
})
export class TenantDetailComponent implements OnInit {
  private fb = inject(FormBuilder);

  tenant: TenantDetail | null = null;
  loading = true;
  error: string | null = null;

  // contact editor: null = closed, 'new' = adding, a contact = editing it
  editingContact: TenantContact | 'new' | null = null;
  savingContact = false;
  contactError: string | null = null;
  contactToDelete: TenantContact | null = null;
  deletingContact = false;

  contactForm = this.fb.group({
    contact_name: ['', [Validators.required, Validators.maxLength(200), Validators.pattern(/\S/)]],
    role: ['', [Validators.maxLength(50)]],
    phone: ['', [Validators.maxLength(30), Validators.pattern(PHONE_PATTERN)]],
    email: ['', [Validators.maxLength(200), Validators.pattern(EMAIL_PATTERN)]],
    is_primary: [false]
  });

  constructor(private route: ActivatedRoute, private tenantService: TenantService) {}

  ngOnInit(): void {
    this.load();
  }

  private get tenantId(): number {
    return Number(this.route.snapshot.paramMap.get('id'));
  }

  load(): void {
    this.tenantService.get(this.tenantId).subscribe({
      next: (tenant) => {
        this.tenant = tenant;
        this.loading = false;
      },
      error: () => {
        this.error = 'Tenant not found.';
        this.loading = false;
      }
    });
  }

  get addressLines(): string[] {
    const t = this.tenant;
    if (!t) {
      return [];
    }
    const cityLine = [t.city, t.state_province, t.postal_code].filter(Boolean).join(', ');
    return [t.address_line1, t.address_line2, cityLine, t.country].filter((l): l is string => !!l);
  }

  // ---------------------------------------------------------------- contacts

  isEditing(contact: TenantContact): boolean {
    return this.editingContact !== 'new' && this.editingContact?.contact_id === contact.contact_id;
  }

  startAddContact(): void {
    this.editingContact = 'new';
    this.contactError = null;
    // the first contact is primary by default
    this.contactForm.reset({ contact_name: '', role: '', phone: '', email: '', is_primary: !this.tenant?.contacts.length });
  }

  startEditContact(contact: TenantContact): void {
    this.editingContact = contact;
    this.contactError = null;
    this.contactForm.reset({
      contact_name: contact.contact_name,
      role: contact.role ?? '',
      phone: contact.phone ?? '',
      email: contact.email ?? '',
      is_primary: contact.is_primary
    });
  }

  cancelContact(): void {
    this.editingContact = null;
    this.contactError = null;
  }

  contactInvalid(name: string): boolean {
    const c = this.contactForm.get(name);
    return !!c && c.invalid && c.touched;
  }

  saveContact(): void {
    if (!this.tenant || this.editingContact === null) {
      return;
    }
    if (this.contactForm.invalid) {
      this.contactForm.markAllAsTouched();
      return;
    }
    const raw = this.contactForm.getRawValue();
    const text = (v: string | null | undefined) => (v && v.trim() ? v.trim() : null);
    const payload: TenantContactInput = {
      contact_name: raw.contact_name!.trim(),
      role: text(raw.role),
      phone: text(raw.phone),
      email: text(raw.email),
      is_primary: !!raw.is_primary
    };
    this.savingContact = true;
    this.contactError = null;
    const request$ =
      this.editingContact === 'new'
        ? this.tenantService.createContact(this.tenant.tenant_id, payload)
        : this.tenantService.updateContact(this.tenant.tenant_id, this.editingContact.contact_id, payload);
    request$.subscribe({
      next: () => {
        this.savingContact = false;
        this.editingContact = null;
        // reload: making one contact primary clears the flag on the others
        this.load();
      },
      error: (err) => {
        this.savingContact = false;
        const detail = err?.error?.detail;
        this.contactError = Array.isArray(detail)
          ? detail.map((d: { msg: string }) => d.msg.replace(/^Value error, /, '')).join('; ')
          : detail || 'Failed to save contact.';
      }
    });
  }

  makePrimary(contact: TenantContact): void {
    if (!this.tenant || contact.is_primary) {
      return;
    }
    const { contact_name, role, phone, email } = contact;
    this.tenantService
      .updateContact(this.tenant.tenant_id, contact.contact_id, { contact_name, role, phone, email, is_primary: true })
      .subscribe({ next: () => this.load() });
  }

  confirmDeleteContact(contact: TenantContact): void {
    this.contactToDelete = contact;
  }

  deleteContactConfirmed(): void {
    if (!this.tenant || !this.contactToDelete) {
      return;
    }
    this.deletingContact = true;
    this.tenantService.deleteContact(this.tenant.tenant_id, this.contactToDelete.contact_id).subscribe({
      next: () => {
        this.deletingContact = false;
        this.contactToDelete = null;
        this.load();
      },
      error: () => {
        this.deletingContact = false;
        this.contactToDelete = null;
      }
    });
  }
}
