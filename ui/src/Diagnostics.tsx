import { ReactNode, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Activity,
  AlertTriangle,
  Camera,
  CheckCircle2,
  ChevronDown,
  Cpu,
  HardDrive,
  Lightbulb,
  MinusCircle,
  Network,
  Play,
  RefreshCw,
  ScrollText,
  Terminal,
  Wrench,
  XCircle,
} from 'lucide-react'
import { api } from './api'
import AssistantPanel, { ExplainButton, useAssistant, useOperatorToken } from './Assistant'
import { relativeTime } from './format'
import type {
  ActionLogEntry,
  DiagnosticCommand,
  DiagnosticResult,
  Probe,
  ProbeReport,
  ProbeState,
} from './types'

type Actions = {
  protect: (action: { label: string, run: (token: string) => Promise<unknown> }) => void
  notify: (message: string, tone?: 'success' | 'warning') => void
  token: string | null
}

const stateMeta: Record<ProbeState, { label: string, icon: typeof CheckCircle2, tone: string }> = {
  ok: { label: 'Healthy', icon: CheckCircle2, tone: 'ok' },
  degraded: { label: 'Degraded', icon: AlertTriangle, tone: 'warn' },
  missing: { label: 'No signal', icon: XCircle, tone: 'fault' },
  disabled: { label: 'Safe off', icon: MinusCircle, tone: 'muted' },
  not_installed: { label: 'Not wired', icon: MinusCircle, tone: 'muted' },
  unknown: { label: 'Unknown', icon: AlertTriangle, tone: 'warn' },
}

const categoryMeta: Record<string, { label: string, icon: typeof Cpu }> = {
  bus: { label: 'Sensor buses', icon: Cpu },
  camera: { label: 'Camera', icon: Camera },
  service: { label: 'Services and logs', icon: Activity },
  system: { label: 'System health', icon: HardDrive },
  custom: { label: 'Appliance-specific', icon: Network },
}

/** Order that matches the physical bring-up sequence in docs/VALIDATION.md. */
const stateWeight: Record<ProbeState, number> = {
  missing: 0, degraded: 1, unknown: 2, ok: 3, disabled: 4, not_installed: 5,
}

function ProbeCard({ probe, token, aiReady }: { probe: Probe, token: string | null, aiReady: boolean }) {
  const [open, setOpen] = useState(probe.state === 'missing' || probe.state === 'degraded')
  const meta = stateMeta[probe.state] ?? stateMeta.unknown
  const Icon = meta.icon
  const hasHelp = probe.remediation.length > 0
  return (
    <article className={`probe probe-${meta.tone} ${open ? 'probe-open' : ''}`}>
      <button
        className="probe-head"
        onClick={() => setOpen(value => !value)}
        aria-expanded={open}
        disabled={!hasHelp}
      >
        <span className="probe-icon"><Icon size={18} /></span>
        <span className="probe-title">
          <strong>{probe.label}</strong>
          <small>{probe.interface}</small>
        </span>
        <span className="probe-value">{probe.value ?? '--'}</span>
        <span className={`probe-state probe-state-${meta.tone}`}>{meta.label}</span>
        {hasHelp && <ChevronDown className="probe-chevron" size={16} />}
      </button>
      {open && (
        <div className="probe-body">
          <p className="probe-detail">{probe.detail}</p>
          <dl className="probe-facts">
            <div><dt>Expected</dt><dd>{probe.expected}</dd></div>
            <div><dt>Interface</dt><dd>{probe.interface}</dd></div>
          </dl>
          {hasHelp && (
            <div className="probe-help">
              <h4><Wrench size={14} />What to check</h4>
              <ol>{probe.remediation.map(hint => <li key={hint}>{hint}</li>)}</ol>
            </div>
          )}
          {(probe.state === 'missing' || probe.state === 'degraded') && (
            <ExplainButton
              token={token}
              ready={aiReady}
              subject={`${probe.label} (${probe.interface})`}
              detail={probe.detail}
              context={`Expected: ${probe.expected}\nBuilt-in checks: ${probe.remediation.join(' ')}`}
            />
          )}
        </div>
      )}
    </article>
  )
}

function SummaryChips({ report }: { report: ProbeReport }) {
  const order: ProbeState[] = ['missing', 'degraded', 'ok', 'disabled', 'not_installed']
  return (
    <div className="probe-summary">
      {order.map(state => {
        const count = report.summary[state] ?? 0
        if (!count) return null
        const meta = stateMeta[state]
        const Icon = meta.icon
        return (
          <span key={state} className={`summary-chip summary-${meta.tone}`}>
            <Icon size={14} />{count} {meta.label.toLowerCase()}
          </span>
        )
      })}
    </div>
  )
}

function Console({
  history,
  running,
  onClear,
}: {
  history: DiagnosticResult[]
  running: string | null
  onClear: () => void
}) {
  const endRef = useRef<HTMLDivElement>(null)
  useEffect(() => { endRef.current?.scrollIntoView({ block: 'end' }) }, [history, running])
  return (
    <div className="console" role="log" aria-live="polite" aria-label="Diagnostic output">
      <div className="console-bar">
        <span className="console-dots" aria-hidden="true"><i /><i /><i /></span>
        <span className="console-title"><Terminal size={13} />aeroos diagnostics</span>
        <button className="console-clear" onClick={onClear} disabled={!history.length}>Clear</button>
      </div>
      <div className="console-body">
        {!history.length && !running && (
          <p className="console-hint">
            Pick a check on the left. Every command is read-only and its exact argv is shown before it runs.
          </p>
        )}
        {history.map((result, index) => (
          <div className="console-entry" key={`${result.name}-${result.started_at}-${index}`}>
            <div className="console-command">
              <span className="console-prompt">aeroos@chamber:~$</span> {result.command}
            </div>
            <pre className={result.exit_code === 0 ? '' : 'console-failed'}>{result.output}</pre>
            <div className="console-meta">
              <span className={result.exit_code === 0 ? 'exit-ok' : 'exit-bad'}>
                exit {result.exit_code}
              </span>
              <span>{result.duration_ms} ms</span>
              {result.simulated && <span className="console-sim">simulated</span>}
              <span>{relativeTime(result.started_at)}</span>
            </div>
          </div>
        ))}
        {running && (
          <div className="console-entry">
            <div className="console-command">
              <span className="console-prompt">aeroos@chamber:~$</span> {running}
            </div>
            <pre className="console-running">running…</pre>
          </div>
        )}
        <div ref={endRef} />
      </div>
    </div>
  )
}

function ActionLog({ entries }: { entries: ActionLogEntry[] }) {
  if (!entries.length) return <p className="console-hint">No operator actions recorded yet.</p>
  return (
    <ol className="action-log">
      {entries.map(entry => {
        const failed = entry.action.includes('failed') || entry.action.includes('throttled')
        return (
          <li key={entry.id} className={failed ? 'action-failed' : ''}>
            <span className="action-time">{relativeTime(entry.timestamp)}</span>
            <span className="action-name">{entry.action}</span>
            <span className="action-actor">{entry.actor}</span>
            <code>{entry.payload === '{}' ? '' : entry.payload}</code>
          </li>
        )
      })}
    </ol>
  )
}

function Section({ title, subtitle, action, children }: {
  title: string
  subtitle?: string
  action?: ReactNode
  children: ReactNode
}) {
  return (
    <section className="panel">
      <header className="panel-head">
        <div><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div>{action}
      </header>
      {children}
    </section>
  )
}

export default function Diagnostics({ actions }: { actions: Actions }) {
  const { token, unlock, clear } = useOperatorToken(actions)
  const [report, setReport] = useState<ProbeReport | null>(null)
  const [commands, setCommands] = useState<DiagnosticCommand[]>([])
  const [history, setHistory] = useState<DiagnosticResult[]>([])
  const [log, setLog] = useState<ActionLogEntry[]>([])
  const [running, setRunning] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [tab, setTab] = useState<'terminal' | 'audit'>('terminal')
  const { ready: aiReady } = useAssistant(token)

  const handleFailure = useCallback((reason: unknown) => {
    const message = reason instanceof Error ? reason.message : 'Diagnostics unavailable'
    if (message.toLowerCase().includes('session') || message.toLowerCase().includes('authentication')) {
      clear()
    }
    setError(message)
  }, [clear])

  const load = useCallback(async (active: string) => {
    try {
      const [probeReport, commandList, actionLog] = await Promise.all([
        api.probe(active),
        api.diagnosticCommands(active),
        api.actionLog(active),
      ])
      setReport(probeReport)
      setCommands(commandList)
      setLog(actionLog)
      setError('')
    } catch (reason) {
      handleFailure(reason)
    }
  }, [handleFailure])

  useEffect(() => { if (token) load(token) }, [token, load])
  // Bring-up is a live activity: keep the probe view fresh while it is open.
  useEffect(() => {
    if (!token) return
    const interval = window.setInterval(() => {
      api.probe(token).then(setReport).catch(handleFailure)
    }, 5000)
    return () => window.clearInterval(interval)
  }, [token, handleFailure])

  const run = useCallback(async (command: DiagnosticCommand) => {
    if (!token) { unlock(); return }
    setRunning(command.command)
    try {
      const result = await api.runDiagnostic(token, command.name)
      setHistory(current => [...current, result].slice(-25))
      if (result.exit_code !== 0) actions.notify(`${command.label} exited ${result.exit_code}`, 'warning')
    } catch (reason) {
      handleFailure(reason)
    } finally {
      setRunning(null)
    }
  }, [token, unlock, actions, handleFailure])

  const runBusSweep = useCallback(async () => {
    const sweep = commands.filter(command => command.category === 'bus')
    for (const command of sweep) await run(command)
  }, [commands, run])

  const grouped = useMemo(() => {
    const buckets = new Map<string, DiagnosticCommand[]>()
    for (const command of commands) {
      const list = buckets.get(command.category) ?? []
      list.push(command)
      buckets.set(command.category, list)
    }
    return [...buckets.entries()]
  }, [commands])

  const probes = useMemo(
    () => [...(report?.probes ?? [])].sort((a, b) => stateWeight[a.state] - stateWeight[b.state]),
    [report],
  )
  const faults = probes.filter(probe => probe.state === 'missing' || probe.state === 'degraded')

  if (!token) {
    return (
      <div className="page-stack spatial-workspace">
        <div className="empty-state">
          <Terminal />
          <h2>Diagnostics are operator-protected</h2>
          <p>Hardware probes and the console expose appliance internals. Unlock with the operator PIN.</p>
          <button className="button button-primary" onClick={unlock}>Unlock diagnostics</button>
        </div>
      </div>
    )
  }

  return (
    <div className="page-stack spatial-workspace diagnostics-workspace">
      <div className="section-intro">
        <div>
          <span className="eyebrow">Bring-up and fault finding</span>
          <h2>Diagnostics</h2>
          <p>Live sensor health, wiring expectations, and a read-only console for the appliance.</p>
        </div>
        <button className="button button-secondary" onClick={() => load(token)}>
          <RefreshCw size={16} />Re-probe
        </button>
      </div>

      {error && <div className="diag-error"><AlertTriangle size={16} />{error}</div>}

      {faults.length > 0 && (
        <div className="fault-banner">
          <AlertTriangle size={18} />
          <div>
            <strong>{faults.length} sensor{faults.length > 1 ? 's need' : ' needs'} attention</strong>
            <span>{faults.map(probe => probe.label).join(' · ')} — open each card for the wiring checklist.</span>
          </div>
        </div>
      )}

      <Section
        title="Sensor bring-up"
        subtitle="Every measurement the control plane expects, and what to check when it is absent"
        action={report ? <SummaryChips report={report} /> : undefined}
      >
        <div className="probe-list">
          {probes.map(probe => <ProbeCard key={probe.id} probe={probe} token={token} aiReady={aiReady} />)}
          {!probes.length && <p className="console-hint">Probing…</p>}
        </div>
      </Section>

      <div className="diagnostics-console-layout">
        <Section
          title="Checks"
          subtitle="Read-only commands, no shell"
          action={
            <button className="button button-secondary" onClick={runBusSweep} disabled={!!running}>
              <Play size={15} />Sweep buses
            </button>
          }
        >
          <div className="command-groups">
            {grouped.map(([category, list]) => {
              const meta = categoryMeta[category] ?? { label: category, icon: Network }
              const Icon = meta.icon
              return (
                <div className="command-group" key={category}>
                  <h4><Icon size={14} />{meta.label}</h4>
                  {list.map(command => (
                    <button
                      key={command.name}
                      className="command-button"
                      onClick={() => run(command)}
                      disabled={!!running}
                      title={command.description}
                    >
                      <span className="command-label">
                        <strong>{command.label}</strong>
                        <code>{command.command}</code>
                      </span>
                      {!command.available && !report?.simulator && (
                        <span className="command-missing">not installed</span>
                      )}
                      <Play size={14} />
                    </button>
                  ))}
                </div>
              )
            })}
          </div>
        </Section>

        <Section
          title="Console"
          subtitle="Output of the last 25 checks"
          action={
            <div className="tab-switch">
              <button className={tab === 'terminal' ? 'selected' : ''} onClick={() => setTab('terminal')}>
                <Terminal size={14} />Terminal
              </button>
              <button className={tab === 'audit' ? 'selected' : ''} onClick={() => { setTab('audit'); api.actionLog(token).then(setLog).catch(handleFailure) }}>
                <ScrollText size={14} />Audit trail
              </button>
            </div>
          }
        >
          {tab === 'terminal'
            ? <Console history={history} running={running} onClear={() => setHistory([])} />
            : <ActionLog entries={log} />}
        </Section>
      </div>

      <Section
        title="Assistant"
        subtitle="Explain faults, diagnose the whole appliance, or ask about this chamber"
      >
        <AssistantPanel
          token={token}
          actions={actions}
          consoleOutput={history.slice(-4).map(item => `$ ${item.command}\n${item.output}`).join('\n\n')}
        />
      </Section>

      <Section title="Bring-up guidance" subtitle="Order that matches the validation gates">
        <ol className="bringup-steps">
          <li><Lightbulb size={15} /><div><strong>Power and overlays first.</strong> Run <em>Boot configuration</em> and confirm <code>dtparam=i2c_arm=on</code> and the 1-Wire overlay before wiring anything.</div></li>
          <li><Cpu size={15} /><div><strong>One sensor at a time.</strong> Wire it, then <em>Sweep buses</em>. A device that never appears in the scan is wiring, not software.</div></li>
          <li><Camera size={15} /><div><strong>Camera gate last of the inputs.</strong> The gate must pass before the control service starts, so a failure here blocks boot — read <em>Camera gate log</em>.</div></li>
          <li><Wrench size={15} /><div><strong>Relays stay dark.</strong> Both relay lines report “safe off” until <code>actuator_master_enable</code> is set, and that only happens after the dry-output gate passes.</div></li>
        </ol>
      </Section>
    </div>
  )
}
