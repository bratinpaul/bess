import { ChartSpec, TimelineSpec } from '../graphs/chart-spec';

const BLUE = '#2f6fed';
const GREEN = '#12a37f';
const ORANGE = '#e8830c';
const RED = '#d62828';
const TEAL = '#0e9fb3';
const SLATE = '#5b6472';
const GREY = '#9aa1ab';
const AMBER = '#f2b705';

export const WEATHER_CHARTS: ChartSpec[] = [
  {
    id: 'temperature',
    title: 'Temperature & Dew Point',
    yLabel: '°C',
    // min-max band of the readings in each bucket, mean line, dew point from temperature + humidity
    counters: [
      { key: 'temp_min_c', label: 'temp_min_c', color: RED, role: 'bandMin' },
      { key: 'temp_max_c', label: 'temp_max_c', color: RED, role: 'bandMax' },
      { key: 'temp_c', label: 'temp_c', color: RED },
      { key: 'dew_point_c', label: 'dew_point_c', color: TEAL, dashed: true }
    ],
    refLines: [
      { label: 'Max', ref: 'tempMax', color: ORANGE },
      { label: 'Min', ref: 'tempMin', color: BLUE }
    ]
  },
  {
    id: 'solar',
    title: 'Solar Irradiance & Cloud Cover',
    yLabel: 'GHI W/m²',
    y2Label: 'Cloud %',
    counters: [
      { key: 'ghi_wm2', label: 'ghi_wm2', color: AMBER, role: 'area' },
      { key: 'ghi_max_wm2', label: 'ghi_max_wm2', color: ORANGE, dashed: true },
      { key: 'cloud_pct', label: 'cloud_pct', color: SLATE, axis: 'y2' }
    ],
    refLines: [{ label: 'Peak GHI', ref: 'ghiMax', color: ORANGE }],
    y: { min: 0 },
    y2: { min: 0, max: 100 }
  },
  {
    id: 'irradiation',
    title: 'Irradiation per Interval',
    yLabel: 'Wh/m²',
    counters: [{ key: 'irradiation_whm2', label: 'irradiation_whm2', color: AMBER, role: 'bar' }],
    y: { min: 0 }
  },
  {
    id: 'humidity',
    title: 'Relative Humidity',
    yLabel: '%',
    counters: [{ key: 'humidity_pct', label: 'humidity_pct', color: TEAL }],
    y: { min: 0, max: 100 }
  },
  {
    id: 'wind',
    title: 'Wind Speed',
    yLabel: 'm/s',
    counters: [
      { key: 'wind_min_ms', label: 'wind_min_ms', color: GREEN, role: 'bandMin' },
      { key: 'wind_max_ms', label: 'wind_max_ms', color: GREEN, role: 'bandMax' },
      { key: 'wind_ms', label: 'wind_ms', color: GREEN }
    ],
    y: { min: 0 }
  }
];

export const WEATHER_TIMELINES: TimelineSpec[] = [
  {
    id: 'daylight',
    title: 'Day / Night',
    laneLabel: 'Sun',
    colors: { DAYLIGHT: AMBER, NIGHT: GREY }
  }
];
