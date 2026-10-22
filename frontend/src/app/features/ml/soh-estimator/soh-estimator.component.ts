import { CommonModule } from '@angular/common';
import { Component, OnInit, inject } from '@angular/core';
import { FormControl, FormGroup, FormsModule, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { AuthService } from '../../../core/auth/auth.service';

import {
  SohEstimateResponse,
  SohFeatureField,
  SohModelInfo,
  SohModelOption,
  SohSystemOption,
  featureGroupOf
} from '../../../core/models/soh-ml.model';
import { SohMlService } from '../../../core/services/soh-ml.service';

const WHAT_IF_TRAINERS_ONLY = 'What-if predictions are limited to model trainers (Admin, Data Scientist).';

const MODEL_LABELS: Record<string, string> = { xgboost: 'XGBoost', lightgbm: 'LightGBM' };
const GRAIN_LABELS: Record<string, string> = { '5min': '5-minute', hour: 'hourly', day: 'daily' };

interface EstimatorField extends SohFeatureField {
  min: number | null;
  max: number | null;
  mean: number | null;
  importance: number | null;
  /** Module features can be empty in a reading, so they're optional. */
  optional: boolean;
}

interface HistoryEntry {
  at: Date;
  modelLabel: string;
  system: string;
  source: string;
  predicted: number;
  actual: number | null;
  outOfRange: number;
}

@Component({
  selector: 'app-soh-estimator',
  standalone: true,
  imports: [CommonModule, FormsModule, ReactiveFormsModule, RouterLink],
  templateUrl: './soh-estimator.component.html',
  styleUrl: './soh-estimator.component.scss'
})
export class SohEstimatorComponent implements OnInit {
  private auth = inject(AuthService);
  // ---- model choice
  /** Every completed run: base models and the plant-specific models of every battery system. */
  models: SohModelOption[] = [];
  modelKey = '';
  modelsLoaded = false;
  modelsError: string | null = null;

  modelInfo: SohModelInfo | null = null;
  loadingModelInfo = true;
  modelInfoError: string | null = null;

  // ---- the battery system the inputs are read from
  systems: SohSystemOption[] = [];
  systemsError: string | null = null;
  siteId: number | null = null;
  systemId: number | null = null;

  // ---- inputs: exactly the chosen model's features
  fields: EstimatorField[] = [];
  groups: { name: string; fields: EstimatorField[] }[] = [];
  form: FormGroup = new FormGroup({});
  inputSource: string | null = null;
  recordedSoh: number | null = null;

  loadingSample = false;
  loadingMeans = false;
  sampleError: string | null = null;

  predicting = false;
  predictError: string | null = null;
  result: SohEstimateResponse | null = null;
  history: HistoryEntry[] = [];

  constructor(
    private sohMlService: SohMlService,
    private route: ActivatedRoute,
    private router: Router
  ) {}

  ngOnInit(): void {
    // ?model=<run id>&system=<battery system id>, e.g. from the SOH Model Training page
    this.modelKey = this.route.snapshot.queryParamMap.get('model') || '';
    this.loadSystems();
    this.loadModels();
  }

  // ---------------------------------------------------------------- site and battery system

  private loadSystems(): void {
    this.sohMlService.systems().subscribe({
      next: (systems) => {
        this.systems = systems;
        // the system from the URL, else the first battery system that has telemetry
        const wanted = Number(this.route.snapshot.queryParamMap.get('system'));
        const first = systems.find((s) => s.battery_system_id === wanted) ?? systems.find((s) => s.has_telemetry) ?? systems[0];
        if (first) {
          this.siteId = first.site_id;
          this.systemId = first.battery_system_id;
        }
      },
      error: () => (this.systemsError = 'Could not list the sites and battery systems.')
    });
  }

  get sites(): { site_id: number; site_name: string }[] {
    const seen = new Map<number, string>();
    this.systems.forEach((s) => seen.set(s.site_id, s.site_name));
    return Array.from(seen, ([site_id, site_name]) => ({ site_id, site_name }));
  }

  get siteSystems(): SohSystemOption[] {
    return this.systems.filter((s) => s.site_id === this.siteId);
  }

  get system(): SohSystemOption | undefined {
    return this.systems.find((s) => s.battery_system_id === this.systemId);
  }

  onSiteChange(): void {
    const systems = this.siteSystems;
    this.systemId = (systems.find((s) => s.has_telemetry) ?? systems[0])?.battery_system_id ?? null;
    this.onSystemChange();
  }

  /** Inputs belong to one battery system: a new choice clears them (the model stays as chosen). */
  onSystemChange(): void {
    this.clear();
    this.sampleError = null;
  }

  // ---------------------------------------------------------------- model choice

  /** Every completed run. The model is the one in the URL, else the newest base model (else the newest run). */
  private loadModels(): void {
    this.sohMlService.models().subscribe({
      next: (list) => {
        this.models = list.models;
        this.modelsLoaded = true;
        if (!list.models.some((m) => m.key === this.modelKey)) {
          this.modelKey = (list.models.find((m) => m.scope !== 'system') ?? list.models[0])?.key ?? '';
        }
        if (this.modelKey) {
          this.loadModelInfo();
        } else {
          this.loadingModelInfo = false;
        }
      },
      error: () => {
        this.modelsLoaded = true;
        this.modelsError = 'Could not list the models.';
      }
    });
  }

  get selectedOption(): SohModelOption | undefined {
    return this.models.find((m) => m.key === this.modelKey);
  }

  optionLabel(m: SohModelOption): string {
    const scope = m.scope === 'system' ? `plant${m.training_mode === 'finetune' ? ' (fine-tuned #' + m.parent_run_id + ')' : ''}` : 'base';
    const name = `#${m.run_id}${m.run_name ? ' ' + m.run_name : ''} · ${scope} · ${MODEL_LABELS[m.model_type] ?? m.model_type}`;
    const r2 = m.r2 === null || m.r2 === undefined ? '' : ` · R² ${m.r2.toFixed(3)}`;
    return `${name} · ${GRAIN_LABELS[m.grain] ?? m.grain} · ${m.features} features${r2}`;
  }

  /** Plant-specific models, one group per battery system. */
  get plantGroups(): { label: string; models: SohModelOption[] }[] {
    const groups = new Map<string, SohModelOption[]>();
    this.models
      .filter((m) => m.scope === 'system')
      .forEach((m) => groups.set(m.scope_label, [...(groups.get(m.scope_label) ?? []), m]));
    return Array.from(groups, ([label, models]) => ({ label, models }));
  }

  get baseModels(): SohModelOption[] {
    return this.models.filter((m) => m.scope !== 'system');
  }

  selectModel(key: string): void {
    this.modelKey = key;
    this.router.navigate([], { relativeTo: this.route, queryParams: { model: key }, replaceUrl: true });
    this.loadModelInfo();
  }

  private loadModelInfo(): void {
    this.loadingModelInfo = true;
    this.modelInfoError = null;
    this.sohMlService.modelInfo(this.modelKey).subscribe({
      next: (info) => {
        this.modelInfo = info;
        this.buildForm(info);
        this.loadingModelInfo = false;
      },
      error: (err) => {
        this.modelInfoError = err?.status === 0
          ? 'Could not reach the SOH model service. Is it running on port 8100?'
          : err?.error?.detail || 'Could not load this model.';
        this.loadingModelInfo = false;
      }
    });
  }

  /** One input per model feature, with its training range and importance. */
  private buildForm(info: SohModelInfo): void {
    // grouped like the feature groups on the SOH Model Training page
    this.fields = info.features.map((key) => {
      const base: SohFeatureField = {
        key, label: info.feature_labels?.[key] ?? key, unit: '', group: featureGroupOf(key), step: 'any'
      };
      const range = info.feature_ranges?.[key];
      return {
        ...base,
        min: range?.min ?? null,
        max: range?.max ?? null,
        mean: range?.mean ?? null,
        importance: info.feature_importances?.[key] ?? null,
        optional: key.startsWith('mod_')
      };
    });
    const byGroup = new Map<string, EstimatorField[]>();
    for (const field of this.fields) {
      byGroup.set(field.group, [...(byGroup.get(field.group) ?? []), field]);
    }
    this.groups = Array.from(byGroup.entries()).map(([name, fields]) => ({ name, fields }));
    this.form = new FormGroup(
      Object.fromEntries(
        this.fields.map((f) => [f.key, new FormControl<number | null>(null, f.optional ? [] : [Validators.required])])
      )
    );
    this.inputSource = null;
    this.recordedSoh = null;
    this.result = null;
    this.predictError = null;
    this.sampleError = null;
  }

  // ---------------------------------------------------------------- inputs

  loadSample(): void {
    const system = this.system;
    if (!system?.has_telemetry) {
      return;
    }
    this.loadingSample = true;
    this.sampleError = null;
    this.sohMlService.sample(this.modelKey, system.battery_system_id).subscribe({
      next: (sample) => {
        // readable values (the model gets what's in the fields)
        this.form.patchValue(
          Object.fromEntries(Object.entries(sample.values).map(([k, v]) => [k, v === null ? null : this.round(v)]))
        );
        this.inputSource = `${system.system_name} · latest reading ${sample.day.replace('T', ' ').slice(0, 16)}`;
        this.recordedSoh = sample.actual_soh_pct;
        this.result = null;
        this.loadingSample = false;
      },
      error: (err) => {
        this.sampleError = err?.error?.detail || 'Could not load a reading from the database.';
        this.loadingSample = false;
      }
    });
  }

  /** Start from the chosen battery system's average over the model's training data. */
  fillMeans(): void {
    const system = this.system;
    if (!system?.has_telemetry) {
      return;
    }
    this.loadingMeans = true;
    this.sampleError = null;
    this.sohMlService.average(system.battery_system_id, this.modelKey).subscribe({
      next: (avg) => {
        this.form.patchValue(
          Object.fromEntries(Object.entries(avg.values).map(([k, v]) => [k, v === null ? null : this.round(v)]))
        );
        const span = `${(avg.date_from ?? '').slice(0, 10)} – ${(avg.date_to ?? '').slice(0, 10)}`;
        this.inputSource =
          avg.scope === 'training'
            ? `${system.system_name} · training average (${avg.rows} rows, ${span})`
            : `${system.system_name} · average of all its rows (${avg.rows}, ${span}) — it has none in the training data`;
        // the mean SOH recorded over the same rows, to compare with the estimate
        this.recordedSoh = avg.actual_soh_pct;
        this.result = null;
        this.loadingMeans = false;
      },
      error: (err) => {
        this.sampleError = err?.error?.detail || 'Could not average this battery system.';
        this.loadingMeans = false;
      }
    });
  }

  clear(): void {
    this.form.reset();
    this.inputSource = null;
    this.recordedSoh = null;
    this.result = null;
  }

  /** Typing a value makes the inputs your own (no recorded SOH to compare with). */
  markEdited(): void {
    if (this.inputSource && !this.inputSource.endsWith('(edited)')) {
      this.inputSource = `${this.inputSource} (edited)`;
      this.recordedSoh = null;
    }
  }

  outside(field: EstimatorField): boolean {
    const v = this.form.get(field.key)?.value;
    if (v === null || v === undefined || v === '' || field.min === null || field.max === null) {
      return false;
    }
    return Number(v) < field.min || Number(v) > field.max;
  }

  get outsideCount(): number {
    return this.fields.filter((f) => this.outside(f)).length;
  }

  // ---------------------------------------------------------------- predict

  predict(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }
    this.predicting = true;
    this.predictError = null;
    this.result = null;
    const raw = this.form.getRawValue() as Record<string, number | string | null>;
    const payload = Object.fromEntries(
      Object.entries(raw).map(([k, v]) => [k, v === null || v === '' ? null : Number(v)])
    ) as Record<string, number | null>;
    if (!this.auth.hasPermission('ml.run:execute')) {
      this.predicting = false;
      this.predictError = WHAT_IF_TRAINERS_ONLY;
      return;
    }
    this.sohMlService.predict(payload, this.modelKey).subscribe({
      next: (result) => {
        this.result = result;
        this.predicting = false;
        this.history = [
          {
            at: new Date(),
            modelLabel: `#${result.run_id} ${MODEL_LABELS[this.modelInfo?.model_type ?? ''] ?? ''}`,
            system: this.system ? `${this.system.site_name} · ${this.system.system_name}` : '—',
            source: this.inputSource ?? 'entered by hand',
            predicted: result.predicted_soh_pct,
            actual: this.recordedSoh,
            outOfRange: result.out_of_range.length
          },
          ...this.history
        ].slice(0, 20);
      },
      error: (err) => {
        const detail = err?.error?.detail;
        this.predictError = Array.isArray(detail)
          ? detail.map((d: { loc: string[]; msg: string }) => `${d.loc?.slice(-1)[0]}: ${d.msg}`).join('; ')
          : detail || 'Prediction failed. Is the model service running?';
        this.predicting = false;
      }
    });
  }

  // ---------------------------------------------------------------- display

  label(key: string): string {
    return this.fields.find((f) => f.key === key)?.label ?? key;
  }

  round(v: number): number {
    return Math.abs(v) >= 100 ? Math.round(v * 10) / 10 : Math.round(v * 10000) / 10000;
  }

  pct(v: number | null): string {
    return v === null ? '' : `${(v * 100).toFixed(1)}%`;
  }
}
