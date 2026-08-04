import { FormEvent, ReactNode, useCallback, useEffect, useMemo, useState } from 'react'
import {
  AlertTriangle,
  Beaker,
  Camera,
  Loader2,
  LockKeyhole,
  MessageSquare,
  RefreshCw,
  Send,
  Sparkles,
  Sprout,
  TriangleAlert,
  X,
} from 'lucide-react'
import { api } from './api'
import { relativeTime } from './format'
import type { AIStatus, Capture, Experiment } from './types'

type Actions = {
  protect: (action: { label: string, run: (token: string) => Promise<unknown> }) => void
  notify: (message: string, tone?: 'success' | 'warning') => void
  token: string | null
}

const SUGGESTIONS = [
  'Why is the DHT22 not reporting?',
  'Summarise the last 24 hours of chamber conditions',
  'What should I check before enabling the actuator master?',
]

/** Model output is advice, never a control action — render it as plain text. */
export function AnswerBlock({ answer }: { answer: string }) {
  return (
    <div className="ai-answer">
      <div className="ai-answer-head"><Sparkles size={13} />Gemini · advisory only</div>
      {answer.split(/\n{2,}/).map((para, index) => <p key={index}>{para}</p>)}
    </div>
  )
}

export function useAssistant(token: string | null) {
  const [status, setStatus] = useState<AIStatus | null>(null)
  const refresh = useCallback(async () => {
    if (!token) return
    try { setStatus(await api.aiStatus(token)) } catch { setStatus(null) }
  }, [token])
  useEffect(() => { refresh() }, [refresh])
  // `ready` is the server's verdict, not a guess assembled in the browser: the
  // simulator serves from a stub with no keys, physical mode cannot.
  return { status, refresh, ready: !!status?.ready }
}

/**
 * The operator session, owned by App so one unlock lights up every AI surface.
 * `clear` only drops the local copy; the server session is revoked on logout.
 */
export function useOperatorToken(actions: Actions) {
  const [cleared, setCleared] = useState(false)
  const token = cleared ? null : actions.token
  useEffect(() => { if (actions.token) setCleared(false) }, [actions.token])
  const unlock = useCallback((label?: unknown) => {
    // Also used directly as an onClick handler, which would pass an event here.
    const reason = typeof label === 'string' ? label : 'Operator access'
    actions.protect({ label: reason, run: async () => { setCleared(false) } })
  }, [actions])
  const clear = useCallback(() => {
    sessionStorage.removeItem('aeroos-token')
    setCleared(true)
  }, [])
  return { token, unlock, clear }
}

/** Inline "explain this" button for a probe fault or a failed console command. */
export function ExplainButton({ token, subject, detail, context, ready }: {
  token: string | null
  subject: string
  detail: string
  context?: string
  ready: boolean
}) {
  const [answer, setAnswer] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  if (!ready) return null

  const run = async () => {
    if (!token) return
    setBusy(true)
    setError('')
    try {
      const result = await api.aiExplain(token, subject, detail, context ?? '')
      setAnswer(result.answer)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Assistant unavailable')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="explain-block">
      {!answer && (
        <button className="link-button explain-trigger" onClick={run} disabled={busy}>
          {busy ? <Loader2 size={13} className="spin" /> : <Sparkles size={13} />}
          {busy ? 'Analysing…' : 'Explain with AI'}
        </button>
      )}
      {error && <p className="form-error">{error}</p>}
      {answer && <AnswerBlock answer={answer} />}
    </div>
  )
}

/**
 * Shell shared by every grow-side AI surface.
 *
 * All four behave the same way on purpose: nothing is generated until the
 * operator presses the button, the result is labelled as advice, and the card
 * says plainly when the assistant is off rather than hiding itself. A panel
 * that quietly disappears reads as a broken build.
 */
function InsightCard({ title, subtitle, icon, actions, ready, status, stored, storedAt, generate, verb, children }: {
  title: string
  subtitle: string
  icon: ReactNode
  actions: Actions
  ready: boolean
  status: AIStatus | null
  stored?: string | null
  storedAt?: string | null
  generate: () => Promise<string>
  verb: string
  children?: ReactNode
}) {
  const [answer, setAnswer] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const shown = answer ?? stored ?? ''
  const run = async () => {
    setBusy(true)
    setError('')
    try {
      setAnswer(await generate())
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Assistant unavailable')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="insight-card">
      <header className="insight-head">
        <span className="insight-icon">{icon}</span>
        <div className="insight-title">
          <strong>{title}</strong>
          <small>{subtitle}</small>
        </div>
        {ready && (
          <button className="button button-compact" onClick={run} disabled={busy}>
            {busy ? <Loader2 size={14} className="spin" /> : shown ? <RefreshCw size={14} /> : <Sparkles size={14} />}
            {busy ? 'Working…' : shown ? 'Regenerate' : verb}
          </button>
        )}
      </header>

      {!ready && (
        <p className="insight-off">
          {!status
            ? <>Unlock the appliance to use AI assistance.</>
            : !status.enabled
              ? <>AI assistance is off. Turn it on in <strong>Settings → AI assistance</strong>; requests send chamber data to Google.</>
              : <>No Gemini keys are configured. Add them to <code>/etc/aeroos/gemini.env</code>.</>}
        </p>
      )}

      {children}
      {error && <div className="diag-error"><AlertTriangle size={15} />{error}</div>}
      {shown && <AnswerBlock answer={shown} />}
      {shown && !answer && storedAt && (
        <small className="insight-stamp">Saved with this record · {relativeTime(storedAt)}</small>
      )}
    </section>
  )
}

/** Home: the chamber's own read on the last 24 hours. */
export function BriefingCard({ token, actions }: { token: string | null, actions: Actions }) {
  const { status, ready } = useAssistant(token)
  const [cached, setCached] = useState<{ answer: string, generated_at: string | null, stale: boolean } | null>(null)

  useEffect(() => {
    if (!token) return
    // A GET never calls the model, so the home screen can render this freely.
    api.briefing(token).then(setCached).catch(() => setCached(null))
  }, [token])

  return (
    <InsightCard
      title="Chamber briefing"
      subtitle={cached?.generated_at ? `Generated ${relativeTime(cached.generated_at)}` : 'Last 24 hours, read from this chamber'}
      icon={<Sparkles size={17} />}
      actions={actions}
      ready={ready}
      status={status}
      stored={cached?.answer}
      storedAt={cached?.generated_at}
      verb="Generate briefing"
      generate={async () => {
        if (!token) throw new Error('Unlock the appliance first')
        const result = await api.generateBriefing(token)
        setCached(result)
        return result.answer
      }}
    >
      {cached?.stale && cached.answer && (
        <p className="insight-stale">This briefing is more than six hours old.</p>
      )}
    </InsightCard>
  )
}

/** Chamber: a target envelope for the crop, next to what the chamber holds. */
export function GrowthPlanCard({ token, actions, crop }: {
  token: string | null
  actions: Actions
  crop?: string | null
}) {
  const { status, ready } = useAssistant(token)
  const [stage, setStage] = useState('vegetative')
  const [goal, setGoal] = useState('')

  return (
    <InsightCard
      title="Growth plan"
      subtitle={crop ? `Targets for ${crop}, compared with this chamber` : 'Start an experiment to name the crop'}
      icon={<Sprout size={17} />}
      actions={actions}
      ready={ready && !!crop}
      status={status}
      verb="Suggest targets"
      generate={async () => {
        if (!token) throw new Error('Unlock the appliance first')
        return (await api.growthPlan(token, { stage, goal })).answer
      }}
    >
      {ready && crop && (
        <div className="plan-inputs">
          <label>
            Stage
            <select value={stage} onChange={event => setStage(event.target.value)}>
              <option value="propagation">Propagation</option>
              <option value="vegetative">Vegetative</option>
              <option value="flowering">Flowering</option>
              <option value="harvest">Approaching harvest</option>
            </select>
          </label>
          <label>
            Goal (optional)
            <input
              value={goal}
              onChange={event => setGoal(event.target.value)}
              placeholder="e.g. faster root development"
              maxLength={300}
            />
          </label>
        </div>
      )}
      {ready && crop && (
        <p className="insight-advisory">
          <TriangleAlert size={13} />
          Suggestions only. AeroOS does not adopt them — change setpoints yourself if you agree.
        </p>
      )}
    </InsightCard>
  )
}

/** Vision: root assessment, written back to the capture record. */
export function CaptureAssessment({ token, actions, capture, onUpdated }: {
  token: string | null
  actions: Actions
  capture?: Capture
  onUpdated?: () => void
}) {
  const { status, ready } = useAssistant(token)
  return (
    <InsightCard
      title="Root assessment"
      subtitle={capture ? `Capture from ${relativeTime(capture.captured_at)}` : 'Capture a frame to assess'}
      icon={<Camera size={17} />}
      actions={actions}
      ready={ready && !!capture}
      status={status}
      stored={capture?.ai_assessment}
      storedAt={capture?.ai_assessed_at}
      verb="Assess roots"
      generate={async () => {
        if (!token || !capture) throw new Error('Capture a frame first')
        const result = await api.aiAnalyzeCapture(token, capture.id)
        onUpdated?.()
        return result.answer
      }}
    />
  )
}

/** Experiments: a run summary saved onto the experiment row. */
export function ExperimentReportCard({ token, actions, experiment, onUpdated }: {
  token: string | null
  actions: Actions
  experiment: Experiment
  onUpdated?: () => void
}) {
  const { status, ready } = useAssistant(token)
  return (
    <InsightCard
      title="Run report"
      subtitle={experiment.ai_report_at ? 'Saved to this experiment record' : 'Environment, delivery, and root growth across the run'}
      icon={<Beaker size={17} />}
      actions={actions}
      ready={ready && !!experiment.started_at}
      status={status}
      stored={experiment.ai_report}
      storedAt={experiment.ai_report_at}
      verb="Write report"
      generate={async () => {
        if (!token) throw new Error('Unlock the appliance first')
        const result = await api.experimentReport(token, experiment.id)
        onUpdated?.()
        return result.answer
      }}
    />
  )
}

/**
 * Ask the chamber anything, from any workspace.
 *
 * The dock is deliberately a separate layer rather than a route: the question a
 * grower has is usually about the screen they are already looking at.
 */
export function AskDock({ actions, chamberName }: { actions: Actions, chamberName?: string }) {
  const { token, unlock } = useOperatorToken(actions)

  const { status, ready } = useAssistant(token)
  const [open, setOpen] = useState(false)
  const [question, setQuestion] = useState('')
  const [thread, setThread] = useState<Array<{ question: string, answer: string }>>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const suggestions = useMemo(() => [
    'How did the chamber do overnight?',
    'Is my humidity where it should be?',
    'What should I check today?',
  ], [])

  const ask = async (event: FormEvent) => {
    event.preventDefault()
    const text = question.trim()
    if (!token || !text) return
    setBusy(true)
    setError('')
    setQuestion('')
    try {
      const result = await api.aiAsk(token, text)
      setThread(current => [...current, { question: text, answer: result.answer }])
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Assistant unavailable')
    } finally {
      setBusy(false)
    }
  }

  if (!open) {
    return (
      <button className="ask-launcher" onClick={() => setOpen(true)} aria-label="Ask AeroOS">
        <Sparkles size={17} /><span>Ask</span>
      </button>
    )
  }

  return (
    <aside className="ask-dock" role="dialog" aria-label="Ask AeroOS">
      <header>
        <span className="insight-icon"><MessageSquare size={15} /></span>
        <div className="insight-title">
          <strong>Ask {chamberName || 'AeroOS'}</strong>
          <small>Answers come from this chamber's own data</small>
        </div>
        <button className="icon-button" onClick={() => setOpen(false)} aria-label="Close assistant"><X /></button>
      </header>

      <div className="ask-thread">
        {!token && (
          <div className="ask-empty">
            <LockKeyhole size={20} />
            <p>Unlock the appliance to ask about this chamber.</p>
            <button className="button button-secondary" onClick={() => unlock('AI assistance')}>Unlock</button>
          </div>
        )}
        {token && !ready && (
          <div className="ask-empty">
            <Sparkles size={20} />
            <p>
              {status?.enabled === false
                ? 'AI assistance is off. Turn it on in Settings → AI assistance.'
                : 'No Gemini keys are configured on this appliance.'}
            </p>
          </div>
        )}
        {thread.map((item, index) => (
          <div className="ask-turn" key={index}>
            <p className="ask-question">{item.question}</p>
            <AnswerBlock answer={item.answer} />
          </div>
        ))}
        {busy && <p className="ask-working"><Loader2 size={14} className="spin" />Thinking…</p>}
        {error && <div className="diag-error"><AlertTriangle size={15} />{error}</div>}
      </div>

      {ready && (
        <>
          {!thread.length && (
            <div className="assistant-suggestions">
              {suggestions.map(item => (
                <button key={item} className="suggestion" onClick={() => setQuestion(item)}>{item}</button>
              ))}
            </div>
          )}
          <form className="assistant-ask" onSubmit={ask}>
            <input
              value={question}
              onChange={event => setQuestion(event.target.value)}
              placeholder="Ask about this chamber…"
              maxLength={600}
              autoFocus
            />
            <button className="button button-primary" disabled={busy || !question.trim()} aria-label="Send question">
              <Send size={15} />
            </button>
          </form>
        </>
      )}
      <footer className="ask-footer">Advisory only · cannot mist, dose, or change a safety state</footer>
    </aside>
  )
}

export default function AssistantPanel({ token, actions, consoleOutput }: {
  token: string | null
  actions: Actions
  consoleOutput: string
}) {
  const { status, refresh, ready } = useAssistant(token)
  const [question, setQuestion] = useState('')
  const [answer, setAnswer] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const run = useCallback(async (task: () => Promise<{ answer: string }>) => {
    setBusy(true)
    setError('')
    try {
      setAnswer((await task()).answer)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Assistant unavailable')
    } finally {
      setBusy(false)
      refresh()
    }
  }, [refresh])

  const ask = (event: FormEvent) => {
    event.preventDefault()
    if (!token || !question.trim()) return
    // This panel lives in Diagnostics, so questions are framed for bring-up.
    run(() => api.aiAsk(token, question.trim(), 'hardware'))
  }

  const toggle = () => {
    actions.protect({
      label: status?.enabled ? 'Disable AI assistance' : 'Enable AI assistance',
      run: async (fresh: string) => {
        await api.setAiEnabled(fresh, !status?.enabled)
        await refresh()
      },
    })
  }

  return (
    <div className="assistant">
      <div className="assistant-head">
        <span className="assistant-icon"><Sparkles size={17} /></span>
        <div className="assistant-title">
          <strong>AI assistance</strong>
          <small>
            {status?.configured
              ? `${status.model} · ${status.key_count} key${status.key_count === 1 ? '' : 's'} pooled`
              : 'No Gemini keys configured'}
          </small>
        </div>
        <button
          className={`toggle ${status?.enabled ? 'toggle-on' : ''}`}
          role="switch"
          aria-checked={!!status?.enabled}
          aria-label="Enable AI assistance"
          onClick={toggle}
        >
          <i />
        </button>
      </div>

      <div className="assistant-notice">
        <TriangleAlert size={14} />
        <span>
          Requests send chamber telemetry, log excerpts, and any selected root image to Google.
          Answers are advice: the assistant cannot mist, dose, or change a safety state.
        </span>
      </div>

      {status && status.keys.length > 0 && (
        <div className="key-pool">
          {status.keys.map(key => (
            <span
              key={key.label}
              className={`key-chip ${key.available ? 'key-ready' : 'key-cooling'}`}
              title={`${key.calls} calls · ${key.failures} failures`}
            >
              {key.label}
              {!key.available && ` · ${key.cooldown_seconds}s`}
            </span>
          ))}
        </div>
      )}

      {!status?.configured && (
        <p className="assistant-setup">
          Add up to four keys to <code>/etc/aeroos/gemini.env</code> as
          {' '}<code>AEROOS_GEMINI_KEYS=key1,key2,key3,key4</code>, then restart the service. AeroOS
          rotates them and rests any key that hits its free-tier quota.
        </p>
      )}

      {ready && (
        <>
          <div className="assistant-actions">
            <button
              className="button button-secondary"
              disabled={busy || !token}
              onClick={() => token && run(() => api.aiDiagnose(token, consoleOutput))}
            >
              {busy ? <Loader2 size={15} className="spin" /> : <Sparkles size={15} />}
              Diagnose current faults
            </button>
          </div>

          <form className="assistant-ask" onSubmit={ask}>
            <input
              value={question}
              onChange={event => setQuestion(event.target.value)}
              placeholder="Ask about this chamber…"
              maxLength={600}
            />
            <button className="button button-primary" disabled={busy || !question.trim()} aria-label="Send question">
              <Send size={15} />
            </button>
          </form>

          <div className="assistant-suggestions">
            {SUGGESTIONS.map(item => (
              <button key={item} className="suggestion" onClick={() => setQuestion(item)}>{item}</button>
            ))}
          </div>
        </>
      )}

      {error && <div className="diag-error"><AlertTriangle size={15} />{error}</div>}
      {status?.last_error && !error && (
        <p className="assistant-setup">Last upstream issue: {status.last_error}</p>
      )}
      {answer && <AnswerBlock answer={answer} />}
    </div>
  )
}
