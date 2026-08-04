import { CSSProperties, FormEvent, ReactNode, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Activity,
  AlertTriangle,
  BarChart3,
  Beaker,
  Bell,
  Camera,
  Check,
  ChevronRight,
  CircleGauge,
  Cpu,
  Database,
  Download,
  Droplets,
  FlaskConical,
  Gauge,
  HardDrive,
  Home,
  Leaf,
  Lightbulb,
  LayoutGrid,
  LockKeyhole,
  Moon,
  Network,
  PanelRightClose,
  PanelRightOpen,
  Power,
  Radio,
  Settings,
  ShieldCheck,
  Sparkles,
  Sprout,
  Sun,
  Terminal,
  TestTube2,
  Thermometer,
  Timer,
  UnlockKeyhole,
  Waves,
  Wifi,
  X,
  Zap,
} from 'lucide-react'
import { NavLink, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { ElevationRequiredError, SessionExpiredError, api } from './api'
import {
  AskDock,
  BriefingCard,
  CaptureAssessment,
  ExperimentReportCard,
  ExplainButton,
  GrowthPlanCard,
  useAssistant,
  useOperatorToken,
} from './Assistant'
import Diagnostics from './Diagnostics'
import NetworkPanel from './Network'
import PinEditor from './PinEditor'
import { formatCountdown, relativeTime } from './format'
import type { Alert, Capture, DashboardData, SensorSnapshot, SystemState, SystemStatus } from './types'

const emptyData: DashboardData = {
  status: null,
  sensors: null,
  history: [],
  alerts: [],
  experiments: [],
  captures: [],
  identity: null,
}

type ProtectedAction = {
  label: string
  run: (token: string) => Promise<unknown>
}

type AppActions = {
  protect: (action: ProtectedAction) => void
  refresh: () => Promise<void>
  notify: (message: string, tone?: 'success' | 'warning') => void
  /** Current operator session. Shared so one unlock lights up every AI surface. */
  token: string | null
}

const navItems = [
  { to: '/', label: 'Home', icon: Home },
  { to: '/chamber', label: 'Chamber', icon: Sprout },
  { to: '/nutrients', label: 'Nutrients', icon: FlaskConical },
  { to: '/vision', label: 'Vision', icon: Camera },
  { to: '/experiments', label: 'Experiments', icon: Beaker },
  { to: '/analytics', label: 'Analytics', icon: BarChart3 },
  { to: '/hardware', label: 'Hardware', icon: Cpu },
  { to: '/diagnostics', label: 'Diagnostics', icon: Terminal },
  { to: '/settings', label: 'Settings', icon: Settings },
]

type ShellSheet = null | 'apps' | 'quick-control' | 'alerts' | 'system'

/** The crop the growth plan should be about: whichever run is active. */
const activeCrop = (data: DashboardData) =>
  data.experiments.find(item => item.state === 'active')?.crop ?? null

const displayNumber = (value: number | null | undefined, digits = 0) =>
  value == null || !Number.isFinite(value) ? '--' : value.toFixed(digits)

const displayPercent = (value: number | null | undefined, digits = 0) =>
  value == null || !Number.isFinite(value) ? 'Unavailable' : `${value.toFixed(digits)}%`

function AeroMark({ compact = false }: { compact?: boolean }) {
  return (
    <div className={`brand ${compact ? 'brand-compact' : ''}`} aria-label="AeroOS">
      <div className="aero-mark" aria-hidden="true">
        <svg viewBox="0 0 48 48">
          <path d="M24 4C18 13 10 20 10 29a14 14 0 0 0 28 0c0-9-8-16-14-25Z" />
          <path className="mark-vein" d="M24 16v21m0-10-7-6m7 11 8-7" />
        </svg>
      </div>
      {!compact && (
        <div>
          <div className="brand-name">AeroOS</div>
          <div className="brand-edition">Chamber control system</div>
        </div>
      )}
    </div>
  )
}

function BootSequence({ onComplete }: { onComplete: () => void }) {
  const [step, setStep] = useState(0)
  const steps = ['Starting control engine', 'Verifying safe hardware', 'Opening chamber']
  useEffect(() => {
    const timers = [
      window.setTimeout(() => setStep(1), 500),
      window.setTimeout(() => setStep(2), 1050),
      window.setTimeout(onComplete, 1600),
    ]
    return () => timers.forEach(window.clearTimeout)
  }, [onComplete])
  return (
    <div className="boot-screen" role="status" aria-live="polite">
      <header className="boot-header">
        <div className="boot-wordmark"><AeroMark compact /><strong>AeroOS</strong></div>
        <span>CHAMBER CONTROL</span>
      </header>
      <main className="boot-main">
        <div className="boot-emblem" aria-hidden="true">
          <svg viewBox="0 0 96 96">
            <path className="boot-drop" d="M48 13C39 29 25 41 25 57a23 23 0 0 0 46 0c0-16-14-28-23-44Z" />
            <path className="boot-vein" d="M48 33v38m0-20-12-10m12 20 14-13" />
            <path className="boot-air boot-air-a" d="M15 31c8-7 15-9 23-8" />
            <path className="boot-air boot-air-b" d="M58 78c9 0 17-3 24-10" />
          </svg>
        </div>
        <span>RESEARCH APPLIANCE</span>
        <h1>Precision chamber control.</h1>
      </main>
      <footer className="boot-footer">
        <div className="boot-stage">
          <span>0{step + 1}</span>
          <strong>{steps[step]}</strong>
          <small>03</small>
        </div>
        <div className="boot-progress" aria-hidden="true"><span style={{ width: `${(step + 1) * 33.33}%` }} /></div>
        <div className="boot-safe"><ShieldCheck /> Outputs remain safely locked during startup</div>
      </footer>
    </div>
  )
}

function StateBadge({ state = 'starting' }: { state?: SystemState }) {
  const labels: Record<SystemState, string> = {
    commissioning: 'Commissioning', starting: 'Starting', safe: 'System safe', active: 'Cycle active',
    degraded: 'Degraded', critical: 'Critical lockout', maintenance: 'Maintenance', shutting_down: 'Shutting down',
  }
  const Icon = state === 'critical' || state === 'degraded' ? AlertTriangle : state === 'active' ? Activity : ShieldCheck
  return <span className={`state-badge state-${state}`}><Icon size={15} />{labels[state]}</span>
}

function AeroSheet({ open, title, subtitle, className = '', onClose, children }: {
  open: boolean
  title: string
  subtitle?: string
  className?: string
  onClose: () => void
  children: ReactNode
}) {
  const panelRef = useRef<HTMLElement>(null)

  useEffect(() => {
    if (!open) return
    const previous = document.activeElement as HTMLElement | null
    const panel = panelRef.current
    const focusable = () => Array.from(panel?.querySelectorAll<HTMLElement>('button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])') || [])
    focusable()[0]?.focus()
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); onClose(); return }
      if (event.key !== 'Tab') return
      const items = focusable()
      if (!items.length) return
      const first = items[0]
      const last = items[items.length - 1]
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
    }
    document.addEventListener('keydown', handleKey)
    return () => { document.removeEventListener('keydown', handleKey); previous?.focus() }
  }, [open, onClose])

  if (!open) return null
  return (
    <div className="sheet-layer" role="presentation" onMouseDown={event => event.target === event.currentTarget && onClose()}>
      <section ref={panelRef} className={`aero-sheet ${className}`} role="dialog" aria-modal="true" aria-labelledby={`sheet-${title.replace(/\s/g, '-').toLowerCase()}`}>
        <header className="sheet-head">
          <div><h2 id={`sheet-${title.replace(/\s/g, '-').toLowerCase()}`}>{title}</h2>{subtitle && <p>{subtitle}</p>}</div>
          <button className="icon-button" onClick={onClose} aria-label={`Close ${title}`}><X /></button>
        </header>
        <div className="sheet-content">{children}</div>
      </section>
    </div>
  )
}

export function AppShell({ data, children, theme, setTheme, actions }: {
  data: DashboardData
  children: ReactNode
  theme: string
  setTheme: (theme: string) => void
  actions: AppActions
}) {
  const [activeSheet, setActiveSheet] = useState<ShellSheet>(null)
  const [clock, setClock] = useState(() => new Date())
  const { ready: aiReady } = useAssistant(actions.token)
  const location = useLocation()
  const navigate = useNavigate()
  const page = navItems.find(item => item.to === location.pathname)?.label || 'Control Center'
  const closeSheet = useCallback(() => setActiveSheet(null), [])

  useEffect(() => { closeSheet() }, [location.pathname, closeSheet])
  useEffect(() => {
    const timer = window.setInterval(() => setClock(new Date()), 30000)
    return () => window.clearInterval(timer)
  }, [])

  const openRoute = (to: string) => { closeSheet(); navigate(to) }
  const toggleSheet = (sheet: Exclude<ShellSheet, null>) => setActiveSheet(current => current === sheet ? null : sheet)
  const sensors = data.sensors
  const isCritical = data.status?.state === 'critical'
  const developmentMode = Boolean(
    data.status && (!data.status.actuators_enabled || data.status.missing_interlocks.length)
  )

  return (
    <div className="os-shell">
      <nav className="os-rail" aria-label="AeroOS controls">
        <div className="rail-brand"><AeroMark compact /></div>
        <div className="rail-primary">
          <NavLink to="/" end className="rail-button" aria-label="Home"><Home /><span>Home</span></NavLink>
          <button className={`rail-button ${activeSheet === 'apps' ? 'selected' : ''}`} onClick={() => toggleSheet('apps')} aria-label="Open app launcher" aria-expanded={activeSheet === 'apps'}><LayoutGrid /><span>Apps</span></button>
          <NavLink to="/chamber" className="rail-button" aria-label="Open chamber"><Sprout /><span>Chamber</span></NavLink>
          <button className={`rail-button rail-mist ${activeSheet === 'quick-control' ? 'selected' : ''}`} onClick={() => toggleSheet('quick-control')} aria-label="Open mist controls" aria-expanded={activeSheet === 'quick-control'}><Droplets /><span>Mist</span></button>
          <NavLink to="/vision" className="rail-button" aria-label="Root vision"><Camera /><span>Vision</span></NavLink>
          <button className={`rail-button rail-alert ${activeSheet === 'alerts' ? 'selected' : ''}`} onClick={() => toggleSheet('alerts')} aria-label={`${data.status?.open_alerts || 0} open alerts`} aria-expanded={activeSheet === 'alerts'}><Bell />{Boolean(data.status?.open_alerts) && <b>{data.status?.open_alerts}</b>}<span>Alerts</span></button>
        </div>
        <div className="rail-system">
          <button className="rail-button" onClick={() => setTheme(theme === 'light' ? 'dark' : 'light')} aria-label={`Use ${theme === 'light' ? 'dark' : 'light'} theme`}>{theme === 'light' ? <Moon /> : <Sun />}<span>Theme</span></button>
          <button className={`rail-button ${activeSheet === 'system' ? 'selected' : ''}`} onClick={() => toggleSheet('system')} aria-label="Open system controls" aria-expanded={activeSheet === 'system'}><Settings /><span>System</span></button>
        </div>
      </nav>

      <header className="os-statusbar">
        <div className="status-context"><strong>{data.identity?.chamber_name || 'Research chamber A1'}</strong><span>{page}</span></div>
        <div className="status-system">
          <StateBadge state={data.status?.state} />
          <span className="status-item mode-item"><span className="status-led" />{data.status?.simulator ? 'SIM' : 'PI'}</span>
          <span className="status-item"><Wifi />Local</span>
          <span className="status-item"><Zap />{displayPercent(sensors?.battery_percent)}</span>
          <time>{clock.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</time>
        </div>
      </header>

      {isCritical && <div className="critical-banner" role="alert"><AlertTriangle />Critical lockout · {data.status?.reason || 'Unsafe output condition detected'}</div>}
      {developmentMode && !isCritical && (
        <div className="development-banner" role="status">
          <AlertTriangle />
          <strong>Development / Interlocks unavailable</strong>
          <span>{data.status?.actuators_enabled ? 'Supervised output session required' : 'Relay outputs physically disabled'}</span>
        </div>
      )}
      <main className="workspace">{children}</main>

      <AeroSheet open={activeSheet === 'apps'} title="Applications" subtitle="AeroOS research workspaces" className="launcher-sheet" onClose={closeSheet}>
        <div className="app-launcher">
          {navItems.map(({ to, label, icon: Icon }) => <button key={to} className={location.pathname === to ? 'active' : ''} onClick={() => openRoute(to)}><span><Icon /></span><strong>{label}</strong></button>)}
        </div>
      </AeroSheet>

      <AeroSheet open={activeSheet === 'quick-control'} title="Mist control" subtitle="Safety-bound chamber delivery" onClose={closeSheet}>
        <div className="sheet-hero">
          <div><span>Next scheduled cycle</span><strong><TimeToNext timestamp={data.status?.next_spray_at} /></strong><small>{data.status?.automation_enabled ? 'Automatic recirculation enabled' : 'Automatic recirculation paused'}</small></div>
          <span className={`cycle-orb ${data.status?.pump_active ? 'active' : ''}`}><Droplets /></span>
        </div>
        <AutomaticRecirculationToggle data={data} actions={actions} />
        <div className="sheet-setting-list">
          <SettingRow label="Reservoir" value={displayPercent(sensors?.reservoir_percent)} />
          <SettingRow label="Flow verification" value={sensors?.flow_lpm == null ? 'Not commissioned' : `${sensors.flow_lpm.toFixed(2)} L/min`} />
          <SettingRow label="Automatic profile" value={data.status?.missing_interlocks.length ? '2 s ON / 5 min interval' : 'Commissioned profile'} />
          <SettingRow label="Safety engine" value={!data.status?.actuators_enabled ? 'Outputs disabled' : isCritical ? 'Locked' : 'Ready'} />
          <SettingRow label="Supervised session" value={data.status?.development_session_expires_at ? `Active · ${formatCountdown(data.status.development_session_expires_at, Date.now())}` : 'Disarmed'} />
        </div>
        <div className="sheet-actions">
          {data.status?.development_session_expires_at
            ? <button className="button button-secondary" onClick={() => actions.protect({ label: 'Disarm development session', run: token => api.disarmDevelopmentSession(token) })}><LockKeyhole />Disarm</button>
            : <button className="button button-secondary" disabled={!data.status?.actuators_enabled} onClick={() => actions.protect({ label: 'Arm 30-minute development session', run: token => api.armDevelopmentSession(token) })}><UnlockKeyhole />Arm 30 min</button>}
          <button className="button button-primary" disabled={data.status?.pump_active || isCritical || !data.status?.actuators_enabled || Boolean(data.status?.missing_interlocks.length && !data.status?.development_session_expires_at)} onClick={() => { closeSheet(); actions.protect({ label: 'Start misting', run: token => api.mist(token, data.status?.missing_interlocks.length ? 2 : 5) }) }}><Droplets />{data.status?.pump_active ? 'Misting now' : !data.status?.actuators_enabled ? 'Power phase required' : isCritical ? 'Locked by safety engine' : 'Authorize safe mist'}</button>
        </div>
      </AeroSheet>

      <AeroSheet open={activeSheet === 'alerts'} title="System alerts" subtitle={`${data.status?.open_alerts || 0} open conditions`} onClose={closeSheet}>
        <div className="alert-sheet-list">
          {data.alerts.filter(alert => !alert.resolved_at).length ? data.alerts.filter(alert => !alert.resolved_at).map(alert => <article className={`sheet-alert alert-${alert.severity}`} key={alert.id}><span><AlertTriangle /></span><div><strong>{alert.code.replaceAll('_', ' ')}</strong><p>{alert.message}</p><small>{relativeTime(alert.opened_at)}</small><ExplainButton token={actions.token} subject={alert.code.replaceAll('_', ' ')} detail={alert.message} context={`Severity ${alert.severity}, opened ${alert.opened_at}. Chamber state: ${data.status?.state} — ${data.status?.reason}.`} ready={aiReady} /></div></article>) : <div className="sheet-empty"><ShieldCheck /><strong>No active alerts</strong><p>Control services and hardware checks are within their safe operating range.</p></div>}
        </div>
      </AeroSheet>

      <AeroSheet open={activeSheet === 'system'} title="System" subtitle="AeroOS appliance controls" onClose={closeSheet}>
        <div className="sheet-setting-list">
          <SettingRow label="AeroOS" value={`v${data.status?.version || '0.1.0'}`} />
          <SettingRow label="Hardware" value={data.identity?.hardware || (data.status?.simulator ? 'Simulator' : 'Raspberry Pi')} />
          <SettingRow label="Network" value="Local only" />
          <SettingRow label="Theme" value={theme === 'light' ? 'Daylight' : 'Dark lab'} />
        </div>
        <div className="sheet-actions"><button className="button button-secondary" onClick={() => setTheme(theme === 'light' ? 'dark' : 'light')}>{theme === 'light' ? <Moon /> : <Sun />}Switch theme</button><button className="button button-primary" onClick={() => openRoute('/settings')}><Settings />Open settings</button></div>
      </AeroSheet>
    </div>
  )
}

function Panel({ title, subtitle, action, className = '', children }: {
  title: string
  subtitle?: string
  action?: ReactNode
  className?: string
  children: ReactNode
}) {
  return (
    <section className={`panel ${className}`}>
      <header className="panel-head">
        <div><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div>{action}
      </header>
      {children}
    </section>
  )
}

function Metric({ label, value, unit, meta, icon: Icon, tone = 'blue' }: {
  label: string
  value: ReactNode
  unit?: string
  meta: string
  icon: typeof Thermometer
  tone?: string
}) {
  return (
    <article className={`metric metric-${tone}`}>
      <div className="metric-head"><span>{label}</span><Icon size={18} /></div>
      <div className="metric-value">{value}<small>{unit}</small></div>
      <div className="metric-meta"><span className="metric-tick"><Check size={12} /></span>{meta}</div>
    </article>
  )
}

function TrendChart({ history, metric = 'environment' }: { history: SensorSnapshot[], metric?: 'environment' | 'ec' | 'root' }) {
  const points = history.slice(-28)
  const width = 700
  const height = 225
  const line = (values: Array<number | null>, min: number, max: number) => values.flatMap((value, index) => {
    if (value == null) return []
    const x = 36 + (index / Math.max(values.length - 1, 1)) * (width - 58)
    const y = 18 + (1 - (value - min) / Math.max(max - min, 1)) * (height - 52)
    return [`${x.toFixed(1)},${y.toFixed(1)}`]
  }).join(' ')
  const tempValues = points.map(point => point.air_temperature_c)
  const humidityValues = points.map(point => point.relative_humidity_percent)
  const ecValues = points.map(point => point.ec_ms_cm)
  const primary = metric === 'ec' ? line(ecValues, 1.3, 2.1) : line(tempValues, 22, 32)
  const secondary = metric === 'ec' ? '' : line(humidityValues, 45, 90)
  return (
    <div className="chart-shell">
      <svg className="trend-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={metric === 'ec' ? 'Nutrient EC trend' : 'Temperature and humidity trend'}>
        {[18, 70, 122, 174].map(y => <line key={y} x1="36" x2="678" y1={y} y2={y} className="chart-grid" />)}
        {points.length > 1 && primary ? (
          <>
            <polyline points={primary} className="chart-line chart-line-a" />
            {secondary && <polyline points={secondary} className="chart-line chart-line-b" />}
            <circle cx={primary.split(' ').at(-1)?.split(',')[0]} cy={primary.split(' ').at(-1)?.split(',')[1]} r="4" className="chart-point" />
          </>
        ) : <text x="350" y="110" textAnchor="middle" className="chart-empty">Collecting trend data…</text>}
        <text x="36" y="214" className="chart-label">Earlier</text><text x="638" y="214" className="chart-label">Now</text>
      </svg>
      <div className="chart-legend">
        <span><i className="legend-a" />{metric === 'ec' ? 'EC mS/cm' : 'Temperature °C'}</span>
        {metric !== 'ec' && <span><i className="legend-b" />Humidity %</span>}
      </div>
    </div>
  )
}

function DeliveryPath({ data }: { data: DashboardData }) {
  const active = data.status?.pump_active
  return (
    <div className="delivery-path">
      <div className="system-node">
        <span className="node-icon"><Waves /></span><strong>Shared reservoir</strong><small>{data.sensors?.reservoir_percent == null ? 'Supply + gravity return' : `${data.sensors.reservoir_percent.toFixed(0)}% · supply + return`}</small>
      </div>
      <div className={`flow-line ${active ? 'flowing' : ''}`}><span /></div>
      <div className={`system-node ${active ? 'active' : ''}`}>
        <span className="node-icon"><Gauge /></span><strong>Mist pump</strong><small>{active ? (data.sensors?.flow_lpm == null ? 'Flow unverified' : `${data.sensors.flow_lpm.toFixed(1)} L/min`) : 'Standby'}</small>
      </div>
      <div className={`flow-line ${active ? 'flowing' : ''}`}><span /></div>
      <div className="system-node">
        <span className="node-icon"><Sprout /></span><strong>Root chamber</strong><small>8 nozzles · drains back</small>
      </div>
    </div>
  )
}

function TimeToNext({ timestamp }: { timestamp: string | null | undefined }) {
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    const interval = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(interval)
  }, [])
  return <>{formatCountdown(timestamp, now)}</>
}

function AutomaticRecirculationToggle({ data, actions, compact = false }: {
  data: DashboardData
  actions: AppActions
  compact?: boolean
}) {
  const status = data.status
  const enabled = Boolean(status?.automation_enabled)
  const critical = status?.state === 'critical'
  const disabled = !status?.actuators_enabled || critical
  const supervised = Boolean(status?.missing_interlocks.length)
  const detail = !status?.actuators_enabled
    ? 'Commission and verify the relay output first'
    : supervised
      ? enabled && status?.development_session_expires_at
        ? `2 s every 5 min · expires ${formatCountdown(status.development_session_expires_at, Date.now())}`
        : 'Starts a PIN-protected 30 min session · 2 s every 5 min'
      : 'Scheduled water cycle · root chamber drains back to reservoir'

  return (
    <div className={`recirculation-toggle ${enabled ? 'enabled' : ''} ${compact ? 'compact' : ''}`}>
      <span className="recirculation-copy"><Waves /><span><strong>Automatic recirculation</strong><small>{detail}</small></span></span>
      <button
        type="button"
        role="switch"
        aria-checked={enabled}
        aria-label={`${enabled ? 'Disable' : 'Enable'} automatic recirculation`}
        className="switch-control"
        disabled={disabled}
        onClick={() => actions.protect({
          label: `${enabled ? 'Disable' : 'Enable'} automatic recirculation`,
          run: token => api.automation(token, !enabled),
        })}
      >
        <i />
      </button>
    </div>
  )
}

export function Overview({ data, actions }: { data: DashboardData, actions: AppActions }) {
  const sensor = data.sensors
  const critical = data.status?.state === 'critical'
  const [hardwareOpen, setHardwareOpen] = useState(true)
  const devices = [
    { name: 'Chamber climate', id: 'DHT22 · GPIO18', state: sensor?.air_temperature_c == null ? 'unavailable' : 'online', tone: sensor?.air_temperature_c == null ? 'warning' : 'safe' },
    { name: 'Solution temperature', id: 'DS18B20 · GPIO4', state: sensor?.solution_temperature_c == null ? 'unavailable' : 'online', tone: sensor?.solution_temperature_c == null ? 'warning' : 'safe' },
    { name: 'Ambient light', id: 'TEMT6000 · PCF8591 A0', state: sensor?.light_percent == null ? 'unavailable' : 'online', tone: sensor?.light_percent == null ? 'warning' : 'safe' },
    { name: 'Flow + level interlocks', id: 'Hardware not installed', state: 'not commissioned', tone: 'warning' },
    { name: 'Root camera', id: 'Arducam B0483 · CSI', state: 'live', tone: 'safe' },
  ]
  return (
    <div className={`spatial-home ${hardwareOpen ? '' : 'hardware-collapsed'}`}>
      <section className="spatial-main" aria-label="Aeroponic chamber overview">
        <div className="chamber-map">
          <div className="home-live-feed"><LiveCameraFeed /></div>
          <div className="home-feed-scrim" aria-hidden="true" />
          <span className="home-live-badge"><i /><span>ROOT CAMERA</span><small>LIVE · 720P</small></span>
          <div className="ambient-reading">
            <strong>{displayNumber(sensor?.air_temperature_c)}°C</strong>
            <span><Sun /> Chamber climate</span>
            <small>Target 24–28°C</small>
          </div>

          <div className="map-lines" aria-hidden="true"><i /><i /><i /><i /></div>
          <div className="camera-overlay-controls" aria-label="Chamber camera controls">
            <NavLink to="/vision" className="map-camera">
              <LiveCameraFeed compact />
              <span>Root vision<small>Open live view</small></span>
              <ChevronRight />
            </NavLink>
            <div className="map-node reservoir-node"><Waves /><span>Reservoir</span><small>{displayPercent(sensor?.reservoir_percent)}</small></div>
            <button className={`map-node pump-node ${data.status?.pump_active ? 'active' : ''}`} onClick={() => actions.protect({ label: 'Start misting', run: token => api.mist(token, 2) })} disabled={data.status?.pump_active || critical || !data.status?.actuators_enabled || Boolean(data.status?.missing_interlocks.length && !data.status?.development_session_expires_at)}><Droplets /><span>Mist pump</span><small>{data.status?.pump_active ? 'ACTIVE' : !data.status?.actuators_enabled ? 'POWER HOLD' : critical ? 'LOCKED' : 'Authorize'}</small></button>
            <div className="map-node chamber-node"><Sprout /><span>Root chamber</span><small>8 nozzles</small></div>
          </div>

          <article className="experiment-card">
            <span>ACTIVE EXPERIMENT</span>
            <h1>{data.status?.active_experiment || 'Chamber standby'}</h1>
            <div><small>Protocol<strong>Adaptive mist</strong></small><small>Progress<strong>Day 6 / 14</strong></small></div>
          </article>
        </div>

        <div className="telemetry-tiles">
          <article className="telemetry-tile tile-primary">
            <header><ShieldCheck /><ChevronRight /></header>
            <span>System health</span>
            <strong>94<em>%</em></strong>
            <small>All essential controls are operating within the safe envelope.</small>
          </article>
          <article className="telemetry-tile">
            <header><Activity /><ChevronRight /></header>
            <span>Next mist</span>
            <strong className="tile-countdown"><TimeToNext timestamp={data.status?.next_spray_at} /></strong>
            <small>{data.status?.automation_enabled ? 'Adaptive automation is active.' : 'Automation is currently paused.'}</small>
          </article>
          <article className="telemetry-tile">
            <header><Thermometer /><ChevronRight /></header>
            <span>Temperature</span>
            <strong>{displayNumber(sensor?.air_temperature_c, 1)}<em>°C</em></strong>
            <small>Maintain a stable root-zone environment.</small>
          </article>
          <article className="telemetry-tile">
            <header><FlaskConical /><ChevronRight /></header>
            <span>pH level</span>
            <strong>{displayNumber(sensor?.ph, 2)}</strong>
            <small>Not commissioned; no chemistry value is fabricated.</small>
          </article>
          <article className="telemetry-tile">
            <header><Droplets /><ChevronRight /></header>
            <span>Humidity</span>
            <strong>{displayNumber(sensor?.relative_humidity_percent)}<em>%</em></strong>
            <small>Root-zone moisture and chamber ventilation.</small>
          </article>
          <article className="telemetry-tile">
            <header><Waves /><ChevronRight /></header>
            <span>Reservoir</span>
            <strong>{displayNumber(sensor?.light_percent)}<em>%</em></strong>
            <small>TEMT6000 coarse ambient light telemetry.</small>
          </article>
        </div>

        <BriefingCard token={actions.token} actions={actions} />
      </section>

      {hardwareOpen ? (
        <aside id="device-health-panel" className="device-column" aria-label="Connected hardware">
          <header>
            <div><span>HARDWARE</span><h2>Device health</h2></div>
            <div className="device-header-actions">
              <StateBadge state={data.status?.state} />
              <button className="hardware-toggle" type="button" aria-label="Collapse hardware panel" aria-expanded="true" aria-controls="device-health-panel" onClick={() => setHardwareOpen(false)}><PanelRightClose /></button>
            </div>
          </header>
          <div className="device-list">
            {devices.map(device => (
              <article key={device.name} className={`device-card device-${device.tone}`}>
                <i />
                <div><strong>{device.name}</strong><small>{device.id}</small></div>
                <span>{device.state}</span>
              </article>
            ))}
          </div>
          <section className="device-summary">
            <div><Cpu /><span>Controller<strong>{data.status?.simulator ? 'Simulator' : 'Raspberry Pi'}</strong></span></div>
            <div><Wifi /><span>Network<strong>Local / secure</strong></span></div>
            <button onClick={() => actions.refresh()}>Refresh devices <ChevronRight /></button>
          </section>
        </aside>
      ) : (
        <button className="hardware-restore" type="button" aria-label="Open hardware panel" aria-expanded="false" aria-controls="device-health-panel" onClick={() => setHardwareOpen(true)}>
          <PanelRightOpen /><span>Hardware</span><i>{devices.length}</i>
        </button>
      )}
    </div>
  )
}

function RootPreview({ capture }: { capture?: Capture }) {
  return (
    <div className="root-preview">
      {capture ? <img src={`/api/v1/captures/${capture.id}/image`} alt="Segmented root structure" /> : (
        <svg viewBox="0 0 320 190" role="img" aria-label="Simulated segmented root structure">
          <path d="M160 8c-4 37 8 58-3 89-10 29 4 54-11 86M159 55c-32 18-42 39-48 68m47-45c34 20 43 43 46 69m-50-25c-26 16-32 38-27 63m31-41c24 19 21 46 35 70" />
        </svg>
      )}
      <span className="camera-chip"><Sparkles />Segmentation {capture ? 'complete' : 'preview'}</span>
      <div className="root-readout"><span>Root area</span><strong>{capture?.root_area_px.toLocaleString() || '18,420'} px²</strong><small>+6.2% / 24h</small></div>
    </div>
  )
}

function LiveCameraFeed({ compact = false }: { compact?: boolean }) {
  const [failed, setFailed] = useState(false)
  if (failed) return <span className={`camera-feed-fallback ${compact ? 'compact' : ''}`}><Camera /><small>Feed unavailable</small></span>
  return <img className="live-camera-feed" src="/api/v1/camera/live" alt={compact ? 'Live root camera preview' : 'Live root-zone camera feed'} onError={() => setFailed(true)} />
}

function Chamber({ data, actions }: { data: DashboardData, actions: AppActions }) {
  return (
    <div className="page-stack spatial-workspace chamber-workspace">
      <div className="section-intro"><div><span className="eyebrow">Environmental control</span><h2>Root chamber</h2><p>Closed-loop water delivery: reservoir → pump → roots → return drain → reservoir.</p></div><div className="hero-actions"><AutomaticRecirculationToggle data={data} actions={actions} compact /><button className="button button-primary" disabled={!data.status?.actuators_enabled || !data.status?.development_session_expires_at} onClick={() => actions.protect({ label: 'Run mist test', run: token => api.mist(token, 2) })}><Droplets />Run 2s test</button></div></div>
      <div className="metric-grid four">
        <Metric label="Air temperature" value={displayNumber(data.sensors?.air_temperature_c, 1)} unit="°C" meta="DHT22 · GPIO18" icon={Thermometer} />
        <Metric label="Humidity" value={displayNumber(data.sensors?.relative_humidity_percent)} unit="%" meta="DHT22 · GPIO18" icon={Droplets} tone="cyan" />
        <Metric label="Ambient light" value={displayNumber(data.sensors?.light_percent)} unit="%" meta="TEMT6000 · PCF8591 A0" icon={Lightbulb} tone="amber" />
        <Metric label="Solution" value={displayNumber(data.sensors?.solution_temperature_c, 1)} unit="°C" meta="DS18B20 · GPIO4" icon={Thermometer} tone="violet" />
      </div>
      <div className="two-column">
        <Panel title="Chamber climate" subtitle="Temperature and humidity with mist events"><TrendChart history={data.history} /></Panel>
        <Panel title="Adaptive profile" subtitle="Bounded water-only research defaults">
          <div className="setting-list">
            <SettingRow label="Baseline interval" value="5 min" />
            <SettingRow label="Mist duration" value="2 sec after power phase" />
            <SettingRow label="Hard duration limit" value="2 sec development" />
            <SettingRow label="Missed-cycle watchdog" value="13 min" />
          </div>
          <div className="safety-note"><ShieldCheck /><span><strong>Guardrails active</strong><small>Manual commands cannot bypass the profile</small></span></div>
        </Panel>
      </div>
      <GrowthPlanCard token={actions.token} actions={actions} crop={activeCrop(data)} />
      <Panel title="Closed-loop delivery" subtitle="Reservoir → pump → eight atomizing nozzles → root chamber → gravity return to the same reservoir"><DeliveryPath data={data} /></Panel>
    </div>
  )
}

function Nutrients({ data }: { data: DashboardData, actions: AppActions }) {
  return (
    <div className="page-stack spatial-workspace nutrients-workspace">
      <div className="section-intro"><div><span className="eyebrow">Nutrient intelligence</span><h2>Solution control</h2><p>Chemistry measurement and nutrient dosing are outside this hardware phase.</p></div><button className="button button-primary" disabled><TestTube2 />Not commissioned</button></div>
      <div className="nutrient-hero">
        <div className="radial-gauge" style={{ '--value': '0%' } as CSSProperties}><div><span>EC</span><strong>--</strong><small>Not commissioned</small></div></div>
        <div className="nutrient-copy"><StateBadge state="degraded" /><h2>Chemistry hardware unavailable</h2><p>AeroOS does not convert the 8-bit PCF8591 into a pH or EC instrument. It is reserved for coarse light telemetry, and no chemistry value is fabricated.</p><div className="inline-stats"><span><small>EC</small><strong>Unavailable</strong></span><span><small>pH</small><strong>Unavailable</strong></span><span><small>Solution temperature</small><strong>{displayNumber(data.sensors?.solution_temperature_c, 1)}°C</strong></span></div></div>
      </div>
      <div className="two-column">
        <Panel title="Commissioning state" subtitle="Explicit capability reporting"><div className="setting-list"><SettingRow label="pH sensor" value="Not commissioned" /><SettingRow label="EC sensor" value="Not commissioned" /><SettingRow label="Nutrient pump" value="Unavailable" /><SettingRow label="Mixer" value="Unavailable" /></div></Panel>
        <Panel title="Safety boundary" subtitle="This phase is sensing and imaging only">
          <div className="setting-list"><SettingRow label="PCF8591 role" value="TEMT6000 light only" /><SettingRow label="Chemistry automation" value="Disabled" /><SettingRow label="Automatic pH correction" value="Disabled" /><SettingRow label="Unattended dosing" value="Disabled" /></div>
          <p className="info-callout"><ShieldCheck />Production chemistry requires a dedicated, calibrated interface in a later phase.</p>
        </Panel>
      </div>
    </div>
  )
}

function Vision({ data, actions }: { data: DashboardData, actions: AppActions }) {
  const active = data.captures[0]
  return (
    <div className="page-stack spatial-workspace vision-workspace">
      <div className="section-intro"><div><span className="eyebrow">Computer vision</span><h2>Root camera</h2><p>Frame, capture, and review root development from one operating view.</p></div><div className="hero-actions"><button className="button button-secondary" onClick={() => actions.refresh()}><Radio />Refresh view</button><button className="button button-primary" onClick={() => actions.protect({ label: 'Capture root image', run: api.capture })}><Camera />Capture &amp; analyze</button></div></div>
      <div className="camera-workbench">
        <section className="camera-surface">
          <header>
            <div><span className="camera-status"><i />{data.status?.simulator ? 'SIMULATED CAMERA' : 'CAMERA READY'}</span><strong>Root-zone camera</strong></div>
            <span>{active ? relativeTime(active.captured_at) : 'No capture yet'}</span>
          </header>
          <div className="camera-frame">
            <LiveCameraFeed />
            <div className="camera-gridlines" aria-hidden="true" />
            <span className="camera-mode"><Radio /> LIVE ROOT VIEW</span>
            <span className="camera-resolution">{data.status?.simulator ? 'SIM LIVE · 640×480' : 'LIVE · 1280×720'}</span>
          </div>
          <footer>
            <span><ShieldCheck /> Controlled-light capture</span>
            <button onClick={() => actions.protect({ label: 'Capture root image', run: api.capture })}><Camera />Capture frame</button>
          </footer>
        </section>

        <aside className="vision-inspector">
          <section className="vision-score">
            <span>ROOT AREA</span>
            <strong>{active?.root_area_px.toLocaleString() || '18,420'}<em> px²</em></strong>
            <small>+6.2% estimated growth / 24h</small>
          </section>
          <section className="vision-properties">
            <SettingRow label="Capture quality" value={active?.quality || 'Preview'} />
            <SettingRow label="Background" value="Uniform" />
            <SettingRow label="Lighting drift" value="1.4%" />
            <SettingRow label="Profile" value="Mint v1" />
          </section>
          <CaptureAssessment token={actions.token} actions={actions} capture={active} onUpdated={actions.refresh} />
          <section className="camera-history">
            <header><strong>Recent captures</strong><span>{data.captures.length} stored</span></header>
            <div>{(data.captures.length ? data.captures : [{ id: 0, captured_at: new Date().toISOString(), root_area_px: 18420, quality: 'preview', image_path: '' }]).slice(0, 4).map(item => <article key={item.id}>{item.id ? <img src={`/api/v1/captures/${item.id}/image`} alt="" /> : <Camera />}<span><strong>{item.root_area_px.toLocaleString()} px²</strong><small>{relativeTime(item.captured_at)}</small></span></article>)}</div>
          </section>
        </aside>
      </div>
    </div>
  )
}

function Experiments({ data, actions }: { data: DashboardData, actions: AppActions }) {
  const [creating, setCreating] = useState(false)
  const [name, setName] = useState('')
  const [crop, setCrop] = useState('Mint')
  const [notes, setNotes] = useState('')
  const create = (event: FormEvent) => {
    event.preventDefault()
    setCreating(false)
    actions.protect({ label: 'Start experiment', run: token => api.startExperiment(token, { name, crop, notes }) })
  }
  return (
    <div className="page-stack spatial-workspace experiments-workspace">
      <div className="section-intro"><div><span className="eyebrow">Research workspace</span><h2>Experiments</h2><p>Every control decision remains traceable to a research run.</p></div><button className="button button-primary" disabled={Boolean(data.status?.active_experiment)} title={data.status?.active_experiment ? 'Complete the active experiment first' : undefined} onClick={() => setCreating(true)}><Beaker />New experiment</button></div>
      {data.experiments.map(experiment => <Panel key={experiment.id} title={experiment.name} subtitle={`${experiment.crop} · ${experiment.state}`} action={<div className="panel-actions"><span className={`soft-badge ${experiment.state === 'active' ? 'badge-active' : ''}`}>{experiment.state}</span>{experiment.state === 'active' && <button className="button button-compact" onClick={() => actions.protect({ label: 'Complete experiment', run: token => api.stopExperiment(token, experiment.id) })}>Complete</button>}</div>}>
        <div className="experiment-row"><div><span>Started</span><strong>{experiment.started_at ? new Date(experiment.started_at).toLocaleDateString() : 'Not started'}</strong></div><div><span>Protocol</span><strong>Adaptive mist v1</strong></div><div><span>Records</span><strong>Continuous</strong></div><div><span>Notes</span><strong>{experiment.notes || '—'}</strong></div></div>
        <ExperimentReportCard token={actions.token} actions={actions} experiment={experiment} onUpdated={actions.refresh} />
      </Panel>)}
      {!data.experiments.length && <EmptyState icon={Beaker} title="No experiments yet" text="Create a research run to connect telemetry, captures, and control decisions." />}
      {creating && <div className="dialog-backdrop" role="presentation" onMouseDown={event => event.target === event.currentTarget && setCreating(false)}><div className="dialog" role="dialog" aria-modal="true" aria-labelledby="experiment-title"><button className="icon-button dialog-close" onClick={() => setCreating(false)} aria-label="Close"><X /></button><span className="dialog-icon"><Beaker /></span><span className="eyebrow">Research protocol</span><h2 id="experiment-title">New experiment</h2><p>Create a traceable run. AeroOS will connect telemetry, images, and every control command to it.</p><form onSubmit={create}><label>Experiment name<input autoFocus value={name} onChange={event => setName(event.target.value)} minLength={2} maxLength={80} required /></label><label>Crop<input value={crop} onChange={event => setCrop(event.target.value)} minLength={2} maxLength={80} required /></label><label>Notes<textarea value={notes} onChange={event => setNotes(event.target.value)} maxLength={500} placeholder="Protocol, cultivar, or hypothesis" /></label><button className="button button-primary button-wide" disabled={name.trim().length < 2}><Beaker />Continue to authorization</button></form></div></div>}
    </div>
  )
}

function Analytics({ data, actions }: { data: DashboardData, actions: AppActions }) {
  return (
    <div className="page-stack spatial-workspace analytics-workspace">
      <div className="section-intro"><div><span className="eyebrow">Research intelligence</span><h2>Analytics</h2><p>Align climate, delivery, nutrients, and root growth on one timeline.</p></div><button className="button button-secondary" onClick={() => actions.protect({ label: 'Export telemetry', run: token => api.exportReadings(token) })}><Download />Export CSV</button></div>
      <div className="metric-grid"><Metric label="Samples" value={data.history.length.toString()} meta="Current view" icon={Database} /><Metric label="System availability" value="99.98" unit="%" meta="No missed cycles" icon={Activity} tone="cyan" /><Metric label="Root growth" value="6.2" unit="%" meta="Last 24 hours" icon={Sprout} tone="violet" /></div>
      <Panel title="Experiment timeline" subtitle="Environmental response and delivery activity"><TrendChart history={data.history} /></Panel>
      <Panel title="Research bundle" subtitle="Reproducible export contents"><div className="bundle-grid"><Bundle icon={Database} title="Telemetry" text="Raw and compensated readings" /><Bundle icon={Droplets} title="Control log" text="Commands, reasons, measured outcomes" /><Bundle icon={Camera} title="Image set" text="Originals and root measurements" /><Bundle icon={Settings} title="Configuration" text="Profiles and calibration versions" /></div></Panel>
    </div>
  )
}

// Derived from live capabilities and the latest snapshot rather than a fixed
// table — this view used to report "Commissioned" for hardware that was not
// connected at all.
function buildHardwareRows(data: DashboardData): Array<[string, string, string, string]> {
  const capabilities = data.status?.hardware_capabilities
  const sensors = data.sensors
  const reading = (value: number | null | undefined, unit: string, digits = 1) =>
    value == null ? 'No signal' : `${value.toFixed(digits)} ${unit}`
  const state = (available: boolean | undefined, live: boolean) =>
    !available ? 'Not wired' : live ? 'Reporting' : 'No signal'
  return [
    ['DHT22 chamber sensor', 'BCM18 · pin 12', reading(sensors?.air_temperature_c, '°C'), state(capabilities?.climate, sensors?.air_temperature_c != null)],
    ['TEMT6000 light', 'PCF8591 0x48 · A0', reading(sensors?.light_percent, '%', 0), state(capabilities?.light, sensors?.light_percent != null)],
    ['DS18B20 solution probe', 'BCM4 · pin 7', reading(sensors?.solution_temperature_c, '°C'), state(capabilities?.solution_temperature, sensors?.solution_temperature_c != null)],
    ['Arducam B0483', 'CSI · 1080p15', capabilities?.camera ? 'Live' : '—', state(capabilities?.camera, !!capabilities?.camera)],
    ['Delivery flow', capabilities?.flow ? 'Inline sensor' : 'No hardware', reading(sensors?.flow_lpm, 'L/min', 2), state(capabilities?.flow, sensors?.flow_lpm != null)],
    ['Reservoir level', capabilities?.reservoir_level ? 'Level sensor' : 'No hardware', reading(sensors?.reservoir_percent, '%', 0), state(capabilities?.reservoir_level, sensors?.reservoir_percent != null)],
    ['Mist relay logic', 'BCM17 · pin 11', data.status?.pump_active ? 'Energized' : 'Parked low', capabilities?.mist_output ? 'Armed' : 'Safe off'],
    ['Fan relay logic', 'BCM25 · pin 22', data.status?.fan_active ? 'Energized' : 'Parked low', capabilities?.fan_output ? 'Armed' : 'Safe off'],
  ]
}

function Hardware({ data, actions }: { data: DashboardData, actions: AppActions }) {
  return (
    <div className="page-stack spatial-workspace hardware-workspace">
      <div className="section-intro"><div><span className="eyebrow">Device diagnostics</span><h2>Hardware topology</h2><p>Freshness, calibration, GPIO, and output state in one service view.</p></div><span className="soft-badge badge-active"><Radio />{data.status?.simulator ? 'Simulator connected' : 'Pi 4 connected'}</span></div>
      <div className="hardware-grid">{buildHardwareRows(data).map(([name, bus, value, state]) => <div className={`hardware-row hardware-${state.toLowerCase().replace(/[^a-z]+/g, '-')}`} key={name}><span className="device-symbol"><Cpu /></span><div><strong>{name}</strong><small>{bus}</small></div><span><small>Latest</small>{value}</span><span className="health-state"><i />{state}</span></div>)}</div>
      <div className="section-hint"><Terminal size={15} />Something reading “No signal”? Open <NavLink to="/diagnostics">Diagnostics</NavLink> for the bus scan and the wiring checklist.</div>
      <Panel title="GPIO assignment" subtitle="Written to /etc/aeroos/hardware.toml; applied on the next service restart">
        <PinEditor actions={actions} />
      </Panel>
      <div className="two-column">
        <Panel title="Power & storage" subtitle="Actuator power is intentionally outside this phase"><div className="setting-list"><SettingRow label="Actuator master" value={data.status?.actuators_enabled ? 'Enabled' : 'Disabled'} /><SettingRow label="12 V domain" value="Not connected" /><SettingRow label="Data partition" value="Healthy" /><SettingRow label="Database WAL" value="Active" /></div></Panel>
        <Panel title="Safety controls" subtitle="Critical lockouts require an explicit operator reset"><div className="fault-actions">{data.status?.simulator && <><button className="button button-secondary" onClick={() => actions.protect({ label: 'Simulate zero flow', run: token => api.simulatorFault(token, 'flow', true) })}>Zero flow</button><button className="button button-secondary" onClick={() => actions.protect({ label: 'Simulate low reservoir', run: token => api.simulatorFault(token, 'reservoir', true) })}>Low reservoir</button><button className="button button-secondary" onClick={() => actions.protect({ label: 'Clear simulated faults', run: async token => { await api.simulatorFault(token, 'flow', false); await api.simulatorFault(token, 'reservoir', false) } })}>Clear faults</button></>}<button className="button button-secondary" disabled={data.status?.state !== 'critical'} onClick={() => actions.protect({ label: 'Reset safety lockout', run: token => api.resetSafety(token) })}><ShieldCheck />Reset safety lockout</button></div></Panel>
      </div>
    </div>
  )
}

function SystemSettings({ data, theme, setTheme, actions }: { data: DashboardData, theme: string, setTheme: (theme: string) => void, actions: AppActions }) {
  return (
    <div className="page-stack spatial-workspace settings-workspace">
      <div className="section-intro"><div><span className="eyebrow">AeroOS control center</span><h2>System settings</h2><p>Manage the appliance without leaving the AeroOS shell.</p></div></div>
      <div className="settings-layout">
        <Panel title="Appearance" subtitle="Optimized for daylight and dark-lab operation"><div className="theme-choices"><button className={`theme-choice ${theme === 'light' ? 'selected' : ''}`} onClick={() => setTheme('light')}><Sun /><span>Daylight<strong>High-clarity surfaces</strong></span></button><button className={`theme-choice ${theme === 'dark' ? 'selected' : ''}`} onClick={() => setTheme('dark')}><Moon /><span>Dark lab<strong>Low-light operation</strong></span></button></div></Panel>
        <Panel title="Automatic recirculation" subtitle="Water returns to the same reservoir after passing through the root chamber"><AutomaticRecirculationToggle data={data} actions={actions} /><div className="setting-list"><SettingRow label="Cycle profile" value="2 s ON / 5 min interval" /><SettingRow label="Startup behavior" value="Always starts OFF" /><SettingRow label="Session expiry" value={data.status?.development_session_expires_at ? formatCountdown(data.status.development_session_expires_at, Date.now()) : 'Not armed'} /><SettingRow label="Fan policy" value={data.status?.fan_requested ? 'Requested on · dry run' : 'Standby · dry run'} /></div></Panel>
        <Panel title="Network & access" subtitle="WiFi provisioning and API reachability" className="network-card"><NetworkPanel actions={actions} /><div className="setting-list"><SettingRow label="Hostname" value={data.identity?.hostname || 'aeroos.local'} /><SettingRow label="Operator control" value="PIN protected" /><SettingRow label="Maintenance SSH" value="Disabled" /></div></Panel>
        <Panel title="About AeroOS" subtitle="Purpose-built aeroponic research platform"><div className="about-product"><AeroMark /><p>A dedicated Linux appliance for safe aeroponic control, imaging, and reproducible research.</p></div><div className="setting-list"><SettingRow label="Edition" value={data.identity?.edition || 'Research Preview'} /><SettingRow label="AeroOS version" value={data.identity?.version || '0.1.0'} /><SettingRow label="Hardware" value={data.identity?.hardware || 'Simulator'} /><SettingRow label="Kernel" value={data.identity?.kernel || 'host-simulator'} /></div></Panel>
      </div>
      <Panel title="Power" subtitle="Available on commissioned Raspberry Pi hardware"><div className="power-actions"><button className="button button-secondary" disabled={data.status?.simulator} title={data.status?.simulator ? 'Available on Raspberry Pi' : undefined}><Power />Shut down safely</button><button className="button button-secondary" disabled={data.status?.simulator} title={data.status?.simulator ? 'Available on Raspberry Pi' : undefined}><Activity />Restart AeroOS services</button><button className="button button-secondary" disabled={data.status?.simulator} title={data.status?.simulator ? 'Available on Raspberry Pi' : undefined}><HardDrive />Create support bundle</button></div></Panel>
    </div>
  )
}

function UnlockDialog({ action, onClose, onSuccess, notify, simulator = false }: { action: ProtectedAction | null, onClose: () => void, onSuccess: (token: string) => void, notify: AppActions['notify'], simulator?: boolean }) {
  const [pin, setPin] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  if (!action) return null
  const submit = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError('')
    try {
      const { token } = await api.login(pin)
      sessionStorage.setItem('aeroos-token', token)
      await action.run(token)
      notify(`${action.label} accepted`)
      onSuccess(token)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Command failed')
    } finally { setBusy(false) }
  }
  return (
    <div className="dialog-backdrop" role="presentation" onMouseDown={event => event.target === event.currentTarget && onClose()}>
      <div className="dialog" role="dialog" aria-modal="true" aria-labelledby="unlock-title">
        <button className="icon-button dialog-close" onClick={onClose} aria-label="Close"><X /></button>
        <span className="dialog-icon"><LockKeyhole /></span><span className="eyebrow">Operator authorization</span><h2 id="unlock-title">Confirm {action.label.toLowerCase()}</h2><p>Enter the AeroOS operator PIN. The command will still pass through all safety interlocks.</p>
        <form onSubmit={submit}><label>Operator PIN<input autoFocus inputMode="numeric" pattern="[0-9]*" value={pin} onChange={event => setPin(event.target.value)} placeholder="••••" /></label>{error && <p className="form-error">{error}</p>}<button className="button button-primary button-wide" disabled={busy || pin.length < 4}>{busy ? 'Authorizing…' : <><UnlockKeyhole />Authorize command</>}</button></form>
        {simulator && <small className="demo-hint">Simulator PIN: 0420</small>}
      </div>
    </div>
  )
}

function Toast({ message, tone }: { message: string, tone: string }) {
  return <div className={`toast toast-${tone}`} role="status">{tone === 'success' ? <Check /> : <AlertTriangle />}{message}</div>
}

function Commissioning({ onComplete }: { onComplete: () => Promise<void> }) {
  const [step, setStep] = useState(0)
  const [chamber, setChamber] = useState('Research chamber A1')
  const [pin, setPin] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const finish = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError('')
    try { await api.commission(chamber, pin); await onComplete() }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Commissioning failed') }
    finally { setBusy(false) }
  }
  return (
    <div className="commissioning-shell">
      <header><AeroMark /><span>Step {step + 1} of 3</span></header>
      <div className="commission-track"><span className={step >= 0 ? 'done' : ''} /><span className={step >= 1 ? 'done' : ''} /><span className={step >= 2 ? 'done' : ''} /></div>
      <main>
        {step === 0 && <div className="commission-step"><span className="dialog-icon"><Sparkles /></span><span className="eyebrow">Welcome to AeroOS</span><h1>Turn this Pi into a research appliance.</h1><p>Commissioning establishes the device identity, verifies the safe hardware state, and protects operator controls.</p><div className="commission-features"><Bundle icon={ShieldCheck} title="Safe by default" text="Outputs remain off during setup" /><Bundle icon={Network} title="Local first" text="Runs without cloud services" /><Bundle icon={Beaker} title="Research ready" text="Traceable experiments and exports" /></div><button className="button button-primary" onClick={() => setStep(1)}>Begin commissioning <ChevronRight /></button></div>}
        {step === 1 && <div className="commission-step"><span className="dialog-icon"><CircleGauge /></span><span className="eyebrow">Hardware self-test</span><h1>Core systems are ready.</h1><p>AeroOS detected the control service and confirmed that every simulated output is in its safe off state.</p><div className="self-test-list"><SettingRow label="Control engine" value="Ready" /><SettingRow label="Data partition" value="Healthy" /><SettingRow label="Sensor interface" value="Detected" /><SettingRow label="Actuator outputs" value="Safe off" /><SettingRow label="Touch display" value="Available" /></div><div className="commission-actions"><button className="button" onClick={() => setStep(0)}>Back</button><button className="button button-primary" onClick={() => setStep(2)}>Continue <ChevronRight /></button></div></div>}
        {step === 2 && <form className="commission-step" onSubmit={finish}><span className="dialog-icon"><LockKeyhole /></span><span className="eyebrow">Identity and access</span><h1>Name the chamber and secure control.</h1><p>Monitoring remains visible locally. Misting, dosing, calibration, and system actions require this PIN.</p><label>Chamber name<input value={chamber} onChange={event => setChamber(event.target.value)} required minLength={2} /></label><label>Operator PIN<input value={pin} onChange={event => setPin(event.target.value)} required pattern="[0-9]{4,8}" inputMode="numeric" placeholder="4–8 digits" /></label>{error && <p className="form-error">{error}</p>}<div className="commission-actions"><button type="button" className="button" onClick={() => setStep(1)}>Back</button><button className="button button-primary" disabled={busy || pin.length < 4}>{busy ? 'Commissioning…' : <><Check />Complete setup</>}</button></div></form>}
      </main>
      <footer>Outputs remain disabled until commissioning is complete.</footer>
    </div>
  )
}

function SettingRow({ label, value }: { label: string, value: string }) { return <div className="setting-row"><span>{label}</span><strong>{value}</strong></div> }
function Bundle({ icon: Icon, title, text }: { icon: typeof Database, title: string, text: string }) { return <div className="bundle-item"><span><Icon /></span><div><strong>{title}</strong><small>{text}</small></div></div> }
function EmptyState({ icon: Icon, title, text }: { icon: typeof Beaker, title: string, text: string }) { return <div className="empty-state"><Icon /><h2>{title}</h2><p>{text}</p></div> }
export default function App() {
  const [data, setData] = useState<DashboardData>(emptyData)
  const [connected, setConnected] = useState(true)
  const [booting, setBooting] = useState(true)
  const [theme, setThemeState] = useState(localStorage.getItem('aeroos-spatial-theme') || 'light')
  const [pending, setPending] = useState<ProtectedAction | null>(null)
  const [toast, setToast] = useState<{ message: string, tone: 'success' | 'warning' } | null>(null)
  const [token, setToken] = useState<string | null>(() => sessionStorage.getItem('aeroos-token'))
  const navigate = useNavigate()

  const setTheme = (next: string) => { setThemeState(next); localStorage.setItem('aeroos-spatial-theme', next) }
  useEffect(() => { document.documentElement.dataset.theme = theme }, [theme])

  const refresh = useCallback(async () => {
    const results = await Promise.allSettled([api.status(), api.sensors(), api.history(), api.alerts(), api.experiments(), api.captures(), api.identity()])
    if (results[0].status === 'rejected') { setConnected(false); return }
    setConnected(true)
    setData(current => ({
      status: results[0].status === 'fulfilled' ? results[0].value : current.status,
      sensors: results[1].status === 'fulfilled' ? results[1].value : current.sensors,
      history: results[2].status === 'fulfilled' ? results[2].value : current.history,
      alerts: results[3].status === 'fulfilled' ? results[3].value : current.alerts,
      experiments: results[4].status === 'fulfilled' ? results[4].value : current.experiments,
      captures: results[5].status === 'fulfilled' ? results[5].value : current.captures,
      identity: results[6].status === 'fulfilled' ? results[6].value : current.identity,
    }))
  }, [])

  // The stream already carries the new reading and status, so the poll is only a
  // slow reconciliation pass. Re-fetching all seven endpoints on every SSE frame
  // put roughly three requests a second onto the Pi's SQLite file.
  useEffect(() => { refresh(); const interval = window.setInterval(refresh, 30000); return () => window.clearInterval(interval) }, [refresh])
  useEffect(() => {
    const events = new EventSource('/api/v1/stream')
    const applySensors = (event: MessageEvent) => {
      try {
        const sensors = JSON.parse(event.data).payload as SensorSnapshot
        setData(current => ({ ...current, sensors, history: [...current.history, sensors].slice(-240) }))
        setConnected(true)
      } catch { refresh() }
    }
    const applyStatus = (event: MessageEvent) => {
      try {
        const status = JSON.parse(event.data).payload as SystemStatus
        setData(current => {
          // No event carries the alert table, so the badge could report an open
          // condition the alert sheet did not yet list. Reconcile on the count.
          if (status.open_alerts !== current.status?.open_alerts) {
            api.alerts().then(alerts => setData(latest => ({ ...latest, alerts }))).catch(() => {})
          }
          return { ...current, status }
        })
      } catch { refresh() }
    }
    const reload = () => refresh()
    events.addEventListener('sensor.updated', applySensors)
    events.addEventListener('system.state.changed', applyStatus)
    // Structural changes touch tables the stream does not carry.
    ;['spray.completed', 'spray.failed', 'dose.completed', 'dose.locked', 'capture.completed', 'experiment.changed', 'automation.changed'].forEach(name => events.addEventListener(name, reload))
    return () => events.close()
  }, [refresh])

  const notify = useCallback((message: string, tone: 'success' | 'warning' = 'success') => {
    setToast({ message, tone }); window.setTimeout(() => setToast(null), 3200)
  }, [])
  const protect = useCallback((action: ProtectedAction) => {
    const token = sessionStorage.getItem('aeroos-token')
    if (!token) { setPending(action); return }
    action.run(token).then(() => { notify(`${action.label} accepted`); refresh() }).catch(error => {
      // A lapsed elevation window is not a failure — the operator just has to
      // confirm they are still at the appliance.
      if (error instanceof SessionExpiredError) { sessionStorage.removeItem('aeroos-token'); setToken(null); setPending(action) }
      else if (error instanceof ElevationRequiredError) setPending(action)
      else notify(error instanceof Error ? error.message : 'Command blocked', 'warning')
    })
  }, [notify, refresh])
  const actions = useMemo<AppActions>(() => ({ protect, refresh, notify, token }), [protect, refresh, notify, token])
  const finishBoot = useCallback(() => setBooting(false), [])

  if (booting) return <BootSequence onComplete={finishBoot} />
  if (!connected && !data.status) return <div className="connection-screen"><AeroMark /><Radio /><h1>Control engine unavailable</h1><p>AeroOS is keeping outputs in their safe state while the service reconnects.</p><button className="button button-primary" onClick={refresh}>Retry connection</button></div>
  if (data.status && !data.status.commissioned) return <Commissioning onComplete={refresh} />

  return (
    <>
      <AppShell data={data} theme={theme} setTheme={setTheme} actions={actions}>
        <Routes>
          <Route path="/" element={<Overview data={data} actions={actions} />} />
          <Route path="/chamber" element={<Chamber data={data} actions={actions} />} />
          <Route path="/nutrients" element={<Nutrients data={data} actions={actions} />} />
          <Route path="/vision" element={<Vision data={data} actions={actions} />} />
          <Route path="/experiments" element={<Experiments data={data} actions={actions} />} />
          <Route path="/analytics" element={<Analytics data={data} actions={actions} />} />
          <Route path="/hardware" element={<Hardware data={data} actions={actions} />} />
          <Route path="/diagnostics" element={<Diagnostics actions={actions} />} />
          <Route path="/settings" element={<SystemSettings data={data} theme={theme} setTheme={setTheme} actions={actions} />} />
          <Route path="*" element={<div className="empty-state"><AlertTriangle /><h2>Workspace not found</h2><button className="button" onClick={() => navigate('/')}>Return home</button></div>} />
        </Routes>
      </AppShell>
      <UnlockDialog action={pending} onClose={() => setPending(null)} onSuccess={fresh => { setPending(null); setToken(fresh); refresh() }} notify={notify} simulator={!!data.status?.simulator} />
      <AskDock actions={actions} chamberName={data.identity?.chamber_name} />
      {toast && <Toast {...toast} />}
    </>
  )
}
