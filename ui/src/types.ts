export type SystemState =
  | 'commissioning'
  | 'starting'
  | 'safe'
  | 'active'
  | 'degraded'
  | 'critical'
  | 'maintenance'
  | 'shutting_down'

export interface SystemStatus {
  state: SystemState
  reason: string
  commissioned: boolean
  automation_enabled: boolean
  simulator: boolean
  active_experiment: string | null
  pump_active: boolean
  dosing_active: boolean
  fan_requested: boolean
  fan_active: boolean
  actuators_enabled: boolean
  hardware_capabilities: {
    climate: boolean
    solution_temperature: boolean
    light: boolean
    camera: boolean
    reservoir_level: boolean
    flow: boolean
    ph: boolean
    ec: boolean
    mist_output: boolean
    fan_output: boolean
    nutrient_dosing: boolean
    mixer: boolean
  }
  missing_interlocks: string[]
  development_session_expires_at: string | null
  next_spray_at: string | null
  last_successful_spray_at: string | null
  open_alerts: number
  version: string
  timestamp: string
}

export interface SensorSnapshot {
  timestamp: string
  air_temperature_c: number | null
  relative_humidity_percent: number | null
  light_lux: number | null
  light_percent: number | null
  solution_temperature_c: number | null
  ph: number | null
  ec_ms_cm: number | null
  reservoir_percent: number | null
  flow_lpm: number | null
  power_voltage: number | null
  battery_percent: number | null
}

export interface Alert {
  id: number
  severity: 'info' | 'warning' | 'critical'
  code: string
  message: string
  opened_at: string
  acknowledged_at: string | null
  resolved_at: string | null
}

export interface Experiment {
  id: number
  name: string
  crop: string
  notes: string
  state: string
  started_at: string | null
  ended_at: string | null
  ai_report?: string | null
  ai_report_at?: string | null
}

export interface Capture {
  id: number
  captured_at: string
  image_path: string
  root_area_px: number
  quality: string
  ai_assessment?: string | null
  ai_assessed_at?: string | null
}

export interface Identity {
  product: string
  edition: string
  version: string
  hostname: string
  hardware: string
  kernel: string
  chamber_name: string
}

export type ProbeState = 'ok' | 'degraded' | 'missing' | 'disabled' | 'not_installed' | 'unknown'

export interface Probe {
  id: string
  label: string
  interface: string
  expected: string
  state: ProbeState
  detail: string
  value: string | null
  remediation: string[]
}

export interface ProbeReport {
  generated_at: string
  simulator: boolean
  summary: Record<ProbeState, number>
  probes: Probe[]
}

export interface DiagnosticCommand {
  name: string
  label: string
  description: string
  category: 'bus' | 'camera' | 'service' | 'system' | string
  command: string
  available: boolean
}

export interface DiagnosticResult {
  name: string
  command: string
  exit_code: number
  output: string
  started_at: string
  duration_ms: number
  simulated: boolean
}

export interface ActionLogEntry {
  id: number
  timestamp: string
  actor: string
  action: string
  payload: string
}

export interface WifiNetwork {
  ssid: string
  security: string
  signal: number
  connected: boolean
  known: boolean
}

export interface NetworkStatus {
  available: boolean
  interface: string
  state: string
  ssid: string | null
  address: string | null
  simulated: boolean
  detail?: string
  api_on_lan: boolean
  api_bind_host: string
}

export interface PinEntry {
  field: string
  label: string
  table: string
  key: string
  value: number
  actuator: boolean
}

export interface PinCatalog {
  pins: PinEntry[]
  reserved: Array<{ gpio: number, reason: string }>
  range: { min: number, max: number }
  editable: boolean
  config_path: string
  actuators_enabled: boolean
}

export interface AIKeyStatus {
  label: string
  available: boolean
  cooldown_seconds: number
  calls: number
  failures: number
}

export interface AIStatus {
  enabled: boolean
  configured: boolean
  /** Server-side verdict: a request would be served. The simulator stub counts. */
  ready: boolean
  simulated: boolean
  model: string
  key_count: number
  keys: AIKeyStatus[]
  last_error: string | null
  notice: string
}

export interface AIBriefing {
  answer: string
  generated_at: string | null
  stale: boolean
}

export interface AIGrowthPlan {
  answer: string
  crop: string
  stage: string
  /** Always false: a growth plan is advice the operator applies by hand. */
  applied: boolean
}

export interface DashboardData {
  status: SystemStatus | null
  sensors: SensorSnapshot | null
  history: SensorSnapshot[]
  alerts: Alert[]
  experiments: Experiment[]
  captures: Capture[]
  identity: Identity | null
}
