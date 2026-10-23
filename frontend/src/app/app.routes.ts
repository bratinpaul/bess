import { Routes } from '@angular/router';

import { authGuard, permissionGuard, routeAccessGuard, sessionGuard } from './core/auth/auth.guard';
import { ShellComponent } from './layout/shell/shell.component';

export const routes: Routes = [
  {
    path: 'login',
    loadComponent: () => import('./features/login/login.component').then((m) => m.LoginComponent)
  },
  {
    path: 'signup',
    loadComponent: () => import('./features/signup/signup.component').then((m) => m.SignupComponent)
  },
  {
    path: 'change-password',
    canActivate: [sessionGuard],
    loadComponent: () => import('./features/change-password/change-password.component').then((m) => m.ChangePasswordComponent)
  },
  {
    path: '',
    component: ShellComponent,
    canActivate: [authGuard],
    canActivateChild: [authGuard, routeAccessGuard],
    children: [
      { path: '', redirectTo: 'dashboard/map-view', pathMatch: 'full' },
      {
        path: 'dashboard/operations',
        loadComponent: () =>
          import('./features/operations/operations-dashboard/operations-dashboard.component').then(
            (m) => m.OperationsDashboardComponent
          )
      },
      {
        path: 'dashboard/map-view',
        loadComponent: () =>
          import('./features/dashboard/map-view/map-view.component').then((m) => m.MapViewComponent)
      },
      {
        path: 'plant-view',
        loadComponent: () =>
          import('./features/plant-view/plant-view.component').then((m) => m.PlantViewComponent)
      },
      {
        path: 'asset-hierarchy',
        loadComponent: () =>
          import('./features/asset-hierarchy/asset-hierarchy.component').then((m) => m.AssetHierarchyComponent)
      },
      {
        path: 'tenants',
        loadComponent: () =>
          import('./features/tenant/tenant-list/tenant-list.component').then((m) => m.TenantListComponent)
      },
      {
        path: 'tenants/new',
        loadComponent: () =>
          import('./features/tenant/tenant-form/tenant-form.component').then((m) => m.TenantFormComponent)
      },
      {
        path: 'tenants/:id',
        loadComponent: () =>
          import('./features/tenant/tenant-detail/tenant-detail.component').then((m) => m.TenantDetailComponent)
      },
      {
        path: 'tenants/:id/edit',
        loadComponent: () =>
          import('./features/tenant/tenant-form/tenant-form.component').then((m) => m.TenantFormComponent)
      },
      {
        path: 'sites',
        loadComponent: () =>
          import('./features/site/site-list/site-list.component').then((m) => m.SiteListComponent)
      },
      {
        path: 'sites/new',
        canActivate: [permissionGuard],
        data: { permission: 'master.asset:write' },
        loadComponent: () =>
          import('./features/site/site-form/site-form.component').then((m) => m.SiteFormComponent)
      },
      {
        path: 'sites/:id',
        loadComponent: () =>
          import('./features/site/site-detail/site-detail.component').then((m) => m.SiteDetailComponent)
      },
      {
        path: 'sites/:id/edit',
        canActivate: [permissionGuard],
        data: { permission: 'master.asset:write' },
        loadComponent: () =>
          import('./features/site/site-form/site-form.component').then((m) => m.SiteFormComponent)
      },
      {
        path: 'battery-systems',
        loadComponent: () =>
          import('./features/battery-system/battery-system-list/battery-system-list.component').then(
            (m) => m.BatterySystemListComponent
          )
      },
      {
        path: 'battery-systems/new',
        loadComponent: () =>
          import('./features/battery-system/battery-system-form/battery-system-form.component').then(
            (m) => m.BatterySystemFormComponent
          )
      },
      {
        path: 'battery-systems/:id',
        loadComponent: () =>
          import('./features/battery-system/battery-system-detail/battery-system-detail.component').then(
            (m) => m.BatterySystemDetailComponent
          )
      },
      {
        path: 'battery-systems/:id/edit',
        loadComponent: () =>
          import('./features/battery-system/battery-system-form/battery-system-form.component').then(
            (m) => m.BatterySystemFormComponent
          )
      },
      {
        path: 'battery-containers',
        loadComponent: () =>
          import('./features/battery-container/battery-container-list/battery-container-list.component').then(
            (m) => m.BatteryContainerListComponent
          )
      },
      {
        path: 'battery-containers/new',
        loadComponent: () =>
          import('./features/battery-container/battery-container-form/battery-container-form.component').then(
            (m) => m.BatteryContainerFormComponent
          )
      },
      {
        path: 'battery-containers/:id',
        loadComponent: () =>
          import('./features/battery-container/battery-container-detail/battery-container-detail.component').then(
            (m) => m.BatteryContainerDetailComponent
          )
      },
      {
        path: 'battery-containers/:id/edit',
        loadComponent: () =>
          import('./features/battery-container/battery-container-form/battery-container-form.component').then(
            (m) => m.BatteryContainerFormComponent
          )
      },
      {
        path: 'battery-packs',
        loadComponent: () =>
          import('./features/battery-pack/battery-pack-list/battery-pack-list.component').then(
            (m) => m.BatteryPackListComponent
          )
      },
      {
        path: 'battery-packs/new',
        loadComponent: () =>
          import('./features/battery-pack/battery-pack-form/battery-pack-form.component').then(
            (m) => m.BatteryPackFormComponent
          )
      },
      {
        path: 'battery-packs/:id',
        loadComponent: () =>
          import('./features/battery-pack/battery-pack-detail/battery-pack-detail.component').then(
            (m) => m.BatteryPackDetailComponent
          )
      },
      {
        path: 'battery-packs/:id/edit',
        loadComponent: () =>
          import('./features/battery-pack/battery-pack-form/battery-pack-form.component').then(
            (m) => m.BatteryPackFormComponent
          )
      },
      {
        path: 'battery-modules',
        loadComponent: () =>
          import('./features/battery-module/battery-module-list/battery-module-list.component').then(
            (m) => m.BatteryModuleListComponent
          )
      },
      {
        path: 'battery-modules/new',
        loadComponent: () =>
          import('./features/battery-module/battery-module-form/battery-module-form.component').then(
            (m) => m.BatteryModuleFormComponent
          )
      },
      {
        path: 'battery-modules/:id',
        loadComponent: () =>
          import('./features/battery-module/battery-module-detail/battery-module-detail.component').then(
            (m) => m.BatteryModuleDetailComponent
          )
      },
      {
        path: 'battery-modules/:id/edit',
        loadComponent: () =>
          import('./features/battery-module/battery-module-form/battery-module-form.component').then(
            (m) => m.BatteryModuleFormComponent
          )
      },
      {
        path: 'ems-controllers',
        loadComponent: () =>
          import('./features/ems-controller/ems-controller-list/ems-controller-list.component').then(
            (m) => m.EmsControllerListComponent
          )
      },
      {
        path: 'ems-controllers/new',
        loadComponent: () =>
          import('./features/ems-controller/ems-controller-form/ems-controller-form.component').then(
            (m) => m.EmsControllerFormComponent
          )
      },
      {
        path: 'ems-controllers/:id',
        loadComponent: () =>
          import('./features/ems-controller/ems-controller-detail/ems-controller-detail.component').then(
            (m) => m.EmsControllerDetailComponent
          )
      },
      {
        path: 'ems-controllers/:id/edit',
        loadComponent: () =>
          import('./features/ems-controller/ems-controller-form/ems-controller-form.component').then(
            (m) => m.EmsControllerFormComponent
          )
      },
      {
        path: 'hvac-units',
        loadComponent: () =>
          import('./features/hvac-unit/hvac-unit-list/hvac-unit-list.component').then(
            (m) => m.HvacUnitListComponent
          )
      },
      {
        path: 'hvac-units/new',
        loadComponent: () =>
          import('./features/hvac-unit/hvac-unit-form/hvac-unit-form.component').then(
            (m) => m.HvacUnitFormComponent
          )
      },
      {
        path: 'hvac-units/:id',
        loadComponent: () =>
          import('./features/hvac-unit/hvac-unit-detail/hvac-unit-detail.component').then(
            (m) => m.HvacUnitDetailComponent
          )
      },
      {
        path: 'hvac-units/:id/edit',
        loadComponent: () =>
          import('./features/hvac-unit/hvac-unit-form/hvac-unit-form.component').then(
            (m) => m.HvacUnitFormComponent
          )
      },
      {
        path: 'dam-prices',
        loadComponent: () => import('./features/dam-price/dam-price.component').then((m) => m.DamPriceComponent)
      },
      {
        path: 'as-prices',
        loadComponent: () => import('./features/as-price/as-price.component').then((m) => m.AsPriceComponent)
      },
      {
        path: 'rt-prices',
        loadComponent: () => import('./features/rt-price/rt-price.component').then((m) => m.RtPriceComponent)
      },
      {
        path: 'price-forecasts',
        loadComponent: () =>
          import('./features/market-price-forecast/market-price-forecast.component').then((m) => m.MarketPriceForecastComponent)
      },
      {
        path: 'dispatch/optimization-runs',
        data: { page: 'optimization-runs' },
        loadComponent: () => import('./features/arbitrage-dispatch/dispatch-page.component').then((m) => m.DispatchPageComponent)
      },
      {
        path: 'dispatch/decision-states',
        data: { page: 'decision-states' },
        loadComponent: () => import('./features/arbitrage-dispatch/dispatch-page.component').then((m) => m.DispatchPageComponent)
      },
      {
        path: 'dispatch/dispatch-schedules',
        data: { page: 'dispatch-schedules' },
        loadComponent: () => import('./features/arbitrage-dispatch/dispatch-page.component').then((m) => m.DispatchPageComponent)
      },
      {
        path: 'dispatch/dispatch-outcomes',
        data: { page: 'dispatch-outcomes' },
        loadComponent: () => import('./features/arbitrage-dispatch/dispatch-page.component').then((m) => m.DispatchPageComponent)
      },
      {
        path: 'dispatch/as-awards',
        data: { page: 'as-awards' },
        loadComponent: () => import('./features/arbitrage-dispatch/dispatch-page.component').then((m) => m.DispatchPageComponent)
      },
      {
        path: 'dispatch/price-scenarios',
        data: { page: 'price-scenarios' },
        loadComponent: () => import('./features/arbitrage-dispatch/dispatch-page.component').then((m) => m.DispatchPageComponent)
      },
      {
        path: 'fault/fault-catalog',
        data: { page: 'fault-catalog' },
        loadComponent: () => import('./features/fault/fault-page.component').then((m) => m.FaultPageComponent)
      },
      {
        path: 'fault/fault-signatures',
        data: { page: 'fault-signatures' },
        loadComponent: () => import('./features/fault/fault-page.component').then((m) => m.FaultPageComponent)
      },
      {
        path: 'fault/fault-episodes',
        data: { page: 'fault-episodes' },
        loadComponent: () => import('./features/fault/fault-page.component').then((m) => m.FaultPageComponent)
      },
      {
        path: 'fault/fault-alarm-links',
        data: { page: 'fault-alarm-links' },
        loadComponent: () => import('./features/fault/fault-page.component').then((m) => m.FaultPageComponent)
      },
      {
        path: 'fault/maintenance-actions',
        data: { page: 'maintenance-actions' },
        loadComponent: () => import('./features/fault/fault-page.component').then((m) => m.FaultPageComponent)
      },
      {
        path: 'fault/fault-predictions',
        data: { page: 'fault-predictions' },
        loadComponent: () => import('./features/fault/fault-page.component').then((m) => m.FaultPageComponent)
      },
      {
        path: 'calendar',
        loadComponent: () => import('./features/calendar/calendar.component').then((m) => m.CalendarComponent)
      },
      {
        path: 'aging-snapshots',
        loadComponent: () => import('./features/aging-snapshot/aging-snapshot.component').then((m) => m.AgingSnapshotComponent)
      },
      {
        path: 'capacity-tests',
        loadComponent: () => import('./features/capacity-test/capacity-test.component').then((m) => m.CapacityTestComponent)
      },
      {
        path: 'lifecycle-events',
        loadComponent: () => import('./features/lifecycle-event/lifecycle-event.component').then((m) => m.LifecycleEventComponent)
      },
      {
        path: 'battery-provenance',
        loadComponent: () =>
          import('./features/battery-provenance/battery-provenance.component').then((m) => m.BatteryProvenanceComponent)
      },
      {
        path: 'ocv-curve',
        loadComponent: () => import('./features/ocv-curve/ocv-curve.component').then((m) => m.OcvCurveComponent)
      },
      {
        path: 'current-sensor-cal',
        loadComponent: () =>
          import('./features/current-sensor-cal/current-sensor-cal.component').then((m) => m.CurrentSensorCalComponent)
      },
      {
        path: 'soc-reference',
        loadComponent: () => import('./features/soc-reference/soc-reference.component').then((m) => m.SocReferenceComponent)
      },
      {
        path: 'tariff-bands',
        loadComponent: () =>
          import('./features/tariff-periods/tariff-period-list/tariff-period-list.component').then(
            (m) => m.TariffPeriodListComponent
          )
      },
      {
        path: 'tariff-bands/new',
        loadComponent: () =>
          import('./features/tariff-periods/tariff-period-form/tariff-period-form.component').then(
            (m) => m.TariffPeriodFormComponent
          )
      },
      {
        path: 'tariff-bands/:id/edit',
        loadComponent: () =>
          import('./features/tariff-periods/tariff-period-form/tariff-period-form.component').then(
            (m) => m.TariffPeriodFormComponent
          )
      },
      {
        path: 'alarm-catalog',
        loadComponent: () =>
          import('./features/alarm-catalog/alarm-catalog-list/alarm-catalog-list.component').then(
            (m) => m.AlarmCatalogListComponent
          )
      },
      {
        path: 'alarm-catalog/new',
        loadComponent: () =>
          import('./features/alarm-catalog/alarm-catalog-form/alarm-catalog-form.component').then(
            (m) => m.AlarmCatalogFormComponent
          )
      },
      {
        path: 'alarm-catalog/:id',
        loadComponent: () =>
          import('./features/alarm-catalog/alarm-catalog-detail/alarm-catalog-detail.component').then(
            (m) => m.AlarmCatalogDetailComponent
          )
      },
      {
        path: 'alarm-catalog/:id/edit',
        loadComponent: () =>
          import('./features/alarm-catalog/alarm-catalog-form/alarm-catalog-form.component').then(
            (m) => m.AlarmCatalogFormComponent
          )
      },
      {
        path: 'pcs',
        loadComponent: () => import('./features/pcs/pcs-list/pcs-list.component').then((m) => m.PcsListComponent)
      },
      {
        path: 'pcs/new',
        loadComponent: () => import('./features/pcs/pcs-form/pcs-form.component').then((m) => m.PcsFormComponent)
      },
      {
        path: 'pcs/:id',
        loadComponent: () => import('./features/pcs/pcs-detail/pcs-detail.component').then((m) => m.PcsDetailComponent)
      },
      {
        path: 'pcs/:id/edit',
        loadComponent: () => import('./features/pcs/pcs-form/pcs-form.component').then((m) => m.PcsFormComponent)
      },
      {
        path: 'telemetry/bms',
        loadComponent: () =>
          import('./features/telemetry/bms-telemetry/bms-telemetry.component').then(
            (m) => m.BmsTelemetryComponent
          )
      },
      {
        path: 'telemetry/module',
        loadComponent: () =>
          import('./features/telemetry/module-telemetry/module-telemetry.component').then(
            (m) => m.ModuleTelemetryComponent
          )
      },
      {
        path: 'telemetry/pcs',
        loadComponent: () =>
          import('./features/telemetry/pcs-telemetry/pcs-telemetry.component').then(
            (m) => m.PcsTelemetryComponent
          )
      },
      {
        path: 'telemetry/ems',
        loadComponent: () =>
          import('./features/telemetry/ems-telemetry/ems-telemetry.component').then(
            (m) => m.EmsTelemetryComponent
          )
      },
      {
        path: 'telemetry/alarms',
        loadComponent: () =>
          import('./features/telemetry/alarm-events/alarm-event-list/alarm-event-list.component').then((m) => m.AlarmEventListComponent)
      },
      {
        path: 'telemetry/alarms/new',
        loadComponent: () =>
          import('./features/telemetry/alarm-events/alarm-event-form/alarm-event-form.component').then((m) => m.AlarmEventFormComponent)
      },
      {
        path: 'telemetry/alarms/:alarmId',
        loadComponent: () =>
          import('./features/telemetry/alarm-events/alarm-event-detail/alarm-event-detail.component').then((m) => m.AlarmEventDetailComponent)
      },
      {
        path: 'telemetry/alarms/:alarmId/edit',
        loadComponent: () =>
          import('./features/telemetry/alarm-events/alarm-event-form/alarm-event-form.component').then((m) => m.AlarmEventFormComponent)
      },
      {
        path: 'batch/realtime',
        loadComponent: () =>
          import('./features/batch/realtime-batch/realtime-batch.component').then((m) => m.RealtimeBatchComponent)
      },
      {
        path: 'batch/static',
        loadComponent: () =>
          import('./features/batch/static-batch/static-batch.component').then((m) => m.StaticBatchComponent)
      },
      {
        path: 'batch/history-generator',
        loadComponent: () =>
          import('./features/batch/historical-generator/historical-generator.component').then(
            (m) => m.HistoricalGeneratorComponent
          )
      },
      {
        path: 'batch/historical',
        loadComponent: () =>
          import('./features/batch/historical-load/historical-load.component').then((m) => m.HistoricalLoadComponent)
      },
      {
        path: 'batch/simulator',
        loadComponent: () =>
          import('./features/batch/snapshot-simulator/snapshot-simulator.component').then((m) => m.SnapshotSimulatorComponent)
      },
      {
        path: 'telemetry/dispatch',
        loadComponent: () =>
          import('./features/telemetry/dispatch-events/dispatch-event-list/dispatch-event-list.component').then(
            (m) => m.DispatchEventListComponent
          )
      },
      {
        path: 'telemetry/dispatch/new',
        loadComponent: () =>
          import('./features/telemetry/dispatch-events/dispatch-event-form/dispatch-event-form.component').then(
            (m) => m.DispatchEventFormComponent
          )
      },
      {
        path: 'telemetry/dispatch/:dispatchId',
        loadComponent: () =>
          import('./features/telemetry/dispatch-events/dispatch-event-detail/dispatch-event-detail.component').then(
            (m) => m.DispatchEventDetailComponent
          )
      },
      {
        path: 'telemetry/dispatch/:dispatchId/edit',
        loadComponent: () =>
          import('./features/telemetry/dispatch-events/dispatch-event-form/dispatch-event-form.component').then(
            (m) => m.DispatchEventFormComponent
          )
      },
      {
        path: 'telemetry/demand',
        loadComponent: () =>
          import('./features/telemetry/demand-telemetry/demand-telemetry.component').then((m) => m.DemandTelemetryComponent)
      },
      {
        path: 'telemetry/weather',
        loadComponent: () => import('./features/telemetry/weather/weather.component').then((m) => m.WeatherComponent)
      },
      {
        path: 'forecast-feed/weather',
        loadComponent: () =>
          import('./features/forecast-feed/weather-forecast/weather-forecast.component').then((m) => m.WeatherForecastComponent)
      },
      {
        path: 'telemetry/hvac',
        loadComponent: () =>
          import('./features/telemetry/hvac-telemetry/hvac-telemetry.component').then(
            (m) => m.HvacTelemetryComponent
          )
      },
      {
        path: 'analytics/daily-summary',
        loadComponent: () =>
          import('./features/analytics/daily-summary/daily-summary.component').then(
            (m) => m.DailySummaryComponent
          )
      },
      {
        path: 'analytics/daily-module-summary',
        loadComponent: () =>
          import('./features/analytics/daily-module-summary/daily-module-summary.component').then(
            (m) => m.DailyModuleSummaryComponent
          )
      },
      {
        path: 'analytics/daily-pcs-summary',
        loadComponent: () =>
          import('./features/analytics/daily-pcs-summary/daily-pcs-summary.component').then(
            (m) => m.DailyPcsSummaryComponent
          )
      },
      {
        path: 'analytics/daily-ems-summary',
        loadComponent: () =>
          import('./features/analytics/daily-ems-summary/daily-ems-summary.component').then(
            (m) => m.DailyEmsSummaryComponent
          )
      },
      {
        path: 'analytics/daily-hvac-summary',
        loadComponent: () =>
          import('./features/analytics/daily-hvac-summary/daily-hvac-summary.component').then(
            (m) => m.DailyHvacSummaryComponent
          )
      },
      {
        path: 'ml/training',
        loadComponent: () =>
          import('./features/ml/model-training/model-training.component').then((m) => m.ModelTrainingComponent)
      },
      {
        path: 'ml/weak-module-model',
        loadComponent: () =>
          import('./features/ml/weak-module-model/weak-module-model.component').then((m) => m.WeakModuleModelComponent)
      },
      {
        path: 'ml/mv-anomaly-model',
        loadComponent: () =>
          import('./features/ml/mv-anomaly-model/mv-anomaly-model.component').then((m) => m.MvAnomalyModelComponent)
      },
      {
        path: 'ml/mv-anomaly',
        loadComponent: () => import('./features/ml/mv-anomaly/mv-anomaly.component').then((m) => m.MvAnomalyComponent)
      },
      {
        path: 'ml/weak-modules',
        loadComponent: () =>
          import('./features/ml/weak-module-results/weak-module-results.component').then((m) => m.WeakModuleResultsComponent)
      },
      {
        path: 'ml/soh-estimator',
        loadComponent: () =>
          import('./features/ml/soh-estimator/soh-estimator.component').then((m) => m.SohEstimatorComponent)
      },
      {
        path: 'ml/efficiency-model',
        loadComponent: () =>
          import('./features/ml/efficiency-model/efficiency-model.component').then((m) => m.EfficiencyModelComponent)
      },
      {
        path: 'ml/efficiency-estimator',
        loadComponent: () =>
          import('./features/ml/efficiency-estimator/efficiency-estimator.component').then((m) => m.EfficiencyEstimatorComponent)
      },
      {
        path: 'ml/loss-model',
        loadComponent: () => import('./features/ml/loss-model/loss-model.component').then((m) => m.LossModelComponent)
      },
      {
        path: 'ml/loss-decomposition',
        loadComponent: () =>
          import('./features/ml/loss-decomposition/loss-decomposition.component').then((m) => m.LossDecompositionComponent)
      },
      {
        path: 'ml/netload-forecast-model',
        loadComponent: () =>
          import('./features/ml/netload-forecast-model/netload-forecast-model.component').then((m) => m.NetloadForecastModelComponent)
      },
      {
        path: 'ml/netload-forecast',
        loadComponent: () => import('./features/ml/netload-forecast/netload-forecast.component').then((m) => m.NetloadForecastComponent)
      },
      {
        path: 'ml/price-forecast-model',
        loadComponent: () =>
          import('./features/ml/price-forecast-model/price-forecast-model.component').then((m) => m.PriceForecastModelComponent)
      },
      {
        path: 'ml/price-forecast',
        loadComponent: () =>
          import('./features/ml/price-forecast/price-forecast.component').then((m) => m.PriceForecastComponent)
      },
      {
        path: 'ml/soc-forecast-model',
        loadComponent: () =>
          import('./features/ml/soc-forecast-model/soc-forecast-model.component').then((m) => m.SocForecastModelComponent)
      },
      {
        path: 'ml/soc-forecast',
        loadComponent: () =>
          import('./features/ml/soc-forecast/soc-forecast.component').then((m) => m.SocForecastComponent)
      },
      {
        path: 'ml/soc-estimation-model',
        loadComponent: () =>
          import('./features/ml/soc-estimation-model/soc-estimation-model.component').then((m) => m.SocEstimationModelComponent)
      },
      {
        path: 'ml/soc-estimator',
        loadComponent: () =>
          import('./features/ml/soc-estimator/soc-estimator.component').then((m) => m.SocEstimatorComponent)
      },
      {
        path: 'ml/thermal-forecast-model',
        loadComponent: () =>
          import('./features/ml/thermal-forecast-model/thermal-forecast-model.component').then((m) => m.ThermalForecastModelComponent)
      },
      {
        path: 'ml/thermal-forecast',
        loadComponent: () =>
          import('./features/ml/thermal-forecast/thermal-forecast.component').then((m) => m.ThermalForecastComponent)
      },
      {
        path: 'ml/arbitrage-model',
        loadComponent: () =>
          import('./features/ml/arbitrage-optimizer/arbitrage-optimizer.component').then((m) => m.ArbitrageOptimizerComponent)
      },
      {
        path: 'ml/arbitrage',
        loadComponent: () =>
          import('./features/ml/dispatch-viewer/dispatch-viewer.component').then((m) => m.DispatchViewerComponent)
      },
      {
        path: 'ml/aux-forecast-model',
        loadComponent: () =>
          import('./features/ml/aux-forecast-model/aux-forecast-model.component').then((m) => m.AuxForecastModelComponent)
      },
      {
        path: 'ml/aux-forecast',
        loadComponent: () =>
          import('./features/ml/aux-forecast/aux-forecast.component').then((m) => m.AuxForecastComponent)
      },
      {
        path: 'ml/heat-load-model',
        loadComponent: () =>
          import('./features/ml/heat-load-model/heat-load-model.component').then((m) => m.HeatLoadModelComponent)
      },
      {
        path: 'ml/heat-load',
        loadComponent: () => import('./features/ml/heat-load/heat-load.component').then((m) => m.HeatLoadComponent)
      },
      {
        path: 'ml/hvac-cop-model',
        loadComponent: () => import('./features/ml/hvac-cop-model/hvac-cop-model.component').then((m) => m.HvacCopModelComponent)
      },
      {
        path: 'ml/hvac-cop',
        loadComponent: () => import('./features/ml/hvac-cop/hvac-cop.component').then((m) => m.HvacCopComponent)
      },
      {
        path: 'ml/fault-diag-model',
        loadComponent: () => import('./features/ml/fault-diag-model/fault-diag-model.component').then((m) => m.FaultDiagModelComponent)
      },
      {
        path: 'ml/fault-diag',
        loadComponent: () => import('./features/ml/fault-diag/fault-diag.component').then((m) => m.FaultDiagComponent)
      },
      {
        path: 'ml/rul-model',
        loadComponent: () => import('./features/ml/rul-model/rul-model.component').then((m) => m.RulModelComponent)
      },
      {
        path: 'admin/users',
        loadComponent: () => import('./features/admin/users/users.component').then((m) => m.UsersComponent)
      },
      {
        path: 'admin/roles',
        loadComponent: () => import('./features/admin/roles/roles.component').then((m) => m.RolesComponent)
      },
      {
        path: 'admin/privileges',
        loadComponent: () => import('./features/admin/privileges/privileges.component').then((m) => m.PrivilegesComponent)
      },
      {
        path: 'admin/rbac',
        loadComponent: () => import('./features/admin/rbac-matrix/rbac-matrix.component').then((m) => m.RbacMatrixComponent)
      },
      {
        path: 'admin/activity',
        loadComponent: () => import('./features/admin/activity-log/activity-log.component').then((m) => m.ActivityLogComponent)
      },
      {
        path: 'admin/access-requests',
        loadComponent: () =>
          import('./features/admin/access-requests/access-requests.component').then((m) => m.AccessRequestsComponent)
      },
      {
        path: 'ml/rul',
        loadComponent: () => import('./features/ml/rul/rul.component').then((m) => m.RulComponent)
      }
    ]
  }
];
