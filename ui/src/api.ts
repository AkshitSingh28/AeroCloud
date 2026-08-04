import type {
  ActionLogEntry,
  AIBriefing,
  AIGrowthPlan,
  AIStatus,
  Alert,
  Capture,
  DiagnosticCommand,
  DiagnosticResult,
  Experiment,
  Identity,
  NetworkStatus,
  PinCatalog,
  ProbeReport,
  SensorSnapshot,
  SystemStatus,
  WifiNetwork,
} from './types'

const jsonHeaders = { 'Content-Type': 'application/json' }

/** The session is still valid but the PIN elevation window has lapsed. */
export class ElevationRequiredError extends Error {}

/** The session token is gone or expired entirely. */
export class SessionExpiredError extends Error {}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init)
  if (!response.ok) {
    let detail = `Request failed (${response.status})`
    try {
      const body = await response.json()
      detail = body.detail || detail
    } catch {
      // Keep the HTTP fallback when the response is not JSON.
    }
    if (response.status === 403) throw new ElevationRequiredError(detail)
    if (response.status === 401) throw new SessionExpiredError(detail)
    throw new Error(detail)
  }
  return response.json() as Promise<T>
}

async function download(path: string, token: string, filename: string): Promise<void> {
  const response = await fetch(path, { headers: { Authorization: `Bearer ${token}` } })
  if (!response.ok) {
    let detail = `Request failed (${response.status})`
    try { detail = (await response.json()).detail || detail } catch { /* Keep the HTTP fallback. */ }
    throw new Error(detail)
  }
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(url)
}

export const api = {
  status: () => request<SystemStatus>('/api/v1/status'),
  sensors: () => request<SensorSnapshot>('/api/v1/sensors/latest'),
  history: () => request<SensorSnapshot[]>('/api/v1/history?limit=80'),
  alerts: () => request<Alert[]>('/api/v1/alerts'),
  experiments: () => request<Experiment[]>('/api/v1/experiments'),
  captures: () => request<Capture[]>('/api/v1/captures'),
  identity: () => request<Identity>('/api/v1/system/identity'),
  commission: (chamberName: string, operatorPin: string) => request<{ commissioned: boolean }>('/api/v1/commission', {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify({ chamber_name: chamberName, operator_pin: operatorPin }),
  }),
  login: (pin: string) => request<{ token: string }>('/api/v1/auth/login', {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify({ pin }),
  }),
  mist: (token: string, seconds = 5) => request('/api/v1/mist', {
    method: 'POST',
    headers: { ...jsonHeaders, Authorization: `Bearer ${token}` },
    body: JSON.stringify({ duration_seconds: seconds, reason: 'AeroOS operator command' }),
  }),
  armDevelopmentSession: (token: string) => request<{ armed: boolean, expires_at: string }>('/api/v1/development-session/arm', {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
  }),
  disarmDevelopmentSession: (token: string) => request<{ armed: boolean }>('/api/v1/development-session/disarm', {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
  }),
  dose: (token: string, volume = 1) => request('/api/v1/dose', {
    method: 'POST',
    headers: { ...jsonHeaders, Authorization: `Bearer ${token}` },
    body: JSON.stringify({ volume_ml: volume, reason: 'AeroOS operator command' }),
  }),
  capture: (token: string) => request<Capture>('/api/v1/captures', {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
  }),
  startExperiment: (token: string, experiment: { name: string, crop: string, notes: string }) => request<Experiment>('/api/v1/experiments/start', {
    method: 'POST',
    headers: { ...jsonHeaders, Authorization: `Bearer ${token}` },
    body: JSON.stringify(experiment),
  }),
  stopExperiment: (token: string, experimentId: number) => request<Experiment>(`/api/v1/experiments/${experimentId}/stop`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
  }),
  exportReadings: (token: string) => download('/api/v1/export/readings.csv', token, 'aeroos-readings.csv'),
  automation: (token: string, enabled: boolean) => request<{ enabled: boolean, next_spray_at: string | null, development_session_expires_at: string | null }>(`/api/v1/automation/${enabled}`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
  }),
  resetSafety: (token: string) => request('/api/v1/safety/reset', {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
  }),
  acknowledge: (token: string, alertId: number) => request(`/api/v1/alerts/${alertId}/acknowledge`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
  }),
  simulatorFault: (token: string, fault: string, enabled: boolean) => request(`/api/v1/simulator/fault/${fault}?enabled=${enabled}`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
  }),
  logout: (token: string) => request<{ revoked: boolean }>('/api/v1/auth/logout', {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
  }),
  probe: (token: string) => request<ProbeReport>('/api/v1/diagnostics/probe', {
    headers: { Authorization: `Bearer ${token}` },
  }),
  diagnosticCommands: (token: string) => request<DiagnosticCommand[]>('/api/v1/diagnostics/commands', {
    headers: { Authorization: `Bearer ${token}` },
  }),
  runDiagnostic: (token: string, name: string) => request<DiagnosticResult>(`/api/v1/diagnostics/run/${name}`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
  }),
  actionLog: (token: string, limit = 120) => request<ActionLogEntry[]>(`/api/v1/diagnostics/actions?limit=${limit}`, {
    headers: { Authorization: `Bearer ${token}` },
  }),

  // ---------------------------------------------------------------- network
  networkStatus: (token: string) => request<NetworkStatus>('/api/v1/network/status', {
    headers: { Authorization: `Bearer ${token}` },
  }),
  wifiScan: (token: string) => request<WifiNetwork[]>('/api/v1/network/scan', {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
  }),
  wifiConnect: (token: string, ssid: string, passphrase: string | null) => request<{ connected: boolean, address?: string }>('/api/v1/network/connect', {
    method: 'POST',
    headers: { ...jsonHeaders, Authorization: `Bearer ${token}` },
    body: JSON.stringify({ ssid, passphrase: passphrase || null }),
  }),
  wifiDisconnect: (token: string) => request<{ connected: boolean }>('/api/v1/network/disconnect', {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
  }),
  wifiForget: (token: string, ssid: string) => request<{ forgotten: boolean }>('/api/v1/network/forget', {
    method: 'POST',
    headers: { ...jsonHeaders, Authorization: `Bearer ${token}` },
    body: JSON.stringify({ ssid }),
  }),
  setLanExposure: (token: string, enabled: boolean) => request<{ enabled: boolean, restart_required: boolean, restart_command: string }>(`/api/v1/network/lan-exposure/${enabled}`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
  }),

  // ------------------------------------------------------------------- pins
  pins: (token: string) => request<PinCatalog>('/api/v1/hardware/pins', {
    headers: { Authorization: `Bearer ${token}` },
  }),
  updatePins: (token: string, assignments: Record<string, number>) => request<{ updated: Record<string, number>, warnings: string[], restart_command: string }>('/api/v1/hardware/pins', {
    method: 'PUT',
    headers: { ...jsonHeaders, Authorization: `Bearer ${token}` },
    body: JSON.stringify(assignments),
  }),

  // --------------------------------------------------------------------- ai
  aiStatus: (token: string) => request<AIStatus>('/api/v1/ai/status', {
    headers: { Authorization: `Bearer ${token}` },
  }),
  setAiEnabled: (token: string, enabled: boolean) => request<AIStatus>(`/api/v1/ai/enabled/${enabled}`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
  }),
  aiDiagnose: (token: string, consoleOutput: string, includeHealthy = false) => request<{ answer: string, probes_considered: number }>('/api/v1/ai/diagnose', {
    method: 'POST',
    headers: { ...jsonHeaders, Authorization: `Bearer ${token}` },
    body: JSON.stringify({ console_output: consoleOutput, include_healthy: includeHealthy }),
  }),
  aiExplain: (token: string, subject: string, detail: string, context = '') => request<{ answer: string }>('/api/v1/ai/explain', {
    method: 'POST',
    headers: { ...jsonHeaders, Authorization: `Bearer ${token}` },
    body: JSON.stringify({ subject, detail, context }),
  }),
  aiAsk: (token: string, question: string, scope: 'chamber' | 'hardware' = 'chamber') => request<{ answer: string }>('/api/v1/ai/ask', {
    method: 'POST',
    headers: { ...jsonHeaders, Authorization: `Bearer ${token}` },
    body: JSON.stringify({ question, scope }),
  }),
  aiAnalyzeCapture: (token: string, captureId: number) => request<{ answer: string, capture: Capture }>(`/api/v1/ai/captures/${captureId}`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
  }),

  // Reading the briefing is free; generating one spends a request.
  briefing: (token: string) => request<AIBriefing>('/api/v1/ai/briefing', {
    headers: { Authorization: `Bearer ${token}` },
  }),
  generateBriefing: (token: string) => request<AIBriefing>('/api/v1/ai/briefing', {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
  }),
  growthPlan: (token: string, body: { crop?: string, stage: string, goal: string }) => request<AIGrowthPlan>('/api/v1/ai/growth-plan', {
    method: 'POST',
    headers: { ...jsonHeaders, Authorization: `Bearer ${token}` },
    body: JSON.stringify(body),
  }),
  experimentReport: (token: string, experimentId: number) => request<{ answer: string, experiment: Experiment }>(`/api/v1/ai/experiments/${experimentId}/report`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
  }),
}
