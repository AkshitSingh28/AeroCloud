import { useCallback, useEffect, useMemo, useState } from 'react'
import { AlertTriangle, Check, CircuitBoard, Info, RotateCcw, ShieldAlert } from 'lucide-react'
import { api } from './api'
import type { PinCatalog } from './types'

type Actions = {
  protect: (action: { label: string, run: (token: string) => Promise<unknown> }) => void
  notify: (message: string, tone?: 'success' | 'warning') => void
}

export default function PinEditor({ actions }: { actions: Actions }) {
  const [token, setToken] = useState<string | null>(() => sessionStorage.getItem('aeroos-token'))
  const [catalog, setCatalog] = useState<PinCatalog | null>(null)
  const [draft, setDraft] = useState<Record<string, number>>({})
  const [warnings, setWarnings] = useState<string[]>([])
  const [errors, setErrors] = useState<string[]>([])
  const [restart, setRestart] = useState('')

  const unlock = useCallback(() => {
    actions.protect({ label: 'Pin configuration', run: async (fresh: string) => { setToken(fresh) } })
  }, [actions])

  const load = useCallback(async (active: string) => {
    try {
      const next = await api.pins(active)
      setCatalog(next)
      setDraft(Object.fromEntries(next.pins.map(pin => [pin.field, pin.value])))
      setErrors([])
    } catch (reason) {
      setErrors([reason instanceof Error ? reason.message : 'Could not read the pin map'])
    }
  }, [])

  useEffect(() => { if (token) load(token) }, [token, load])

  const reservedByPin = useMemo(
    () => new Map((catalog?.reserved ?? []).map(entry => [entry.gpio, entry.reason])),
    [catalog],
  )

  const changed = useMemo(() => {
    if (!catalog) return {}
    return Object.fromEntries(
      catalog.pins
        .filter(pin => draft[pin.field] !== pin.value)
        .map(pin => [pin.field, draft[pin.field]]),
    ) as Record<string, number>
  }, [catalog, draft])

  const duplicates = useMemo(() => {
    const counts = new Map<number, number>()
    Object.values(draft).forEach(value => counts.set(value, (counts.get(value) ?? 0) + 1))
    return new Set([...counts.entries()].filter(([, count]) => count > 1).map(([pin]) => pin))
  }, [draft])

  const localProblem = useCallback((field: string, value: number) => {
    if (Number.isNaN(value)) return 'Enter a BCM number'
    if (catalog && (value < catalog.range.min || value > catalog.range.max)) {
      return `Outside BCM${catalog.range.min}–${catalog.range.max}`
    }
    if (reservedByPin.has(value)) return reservedByPin.get(value)
    if (duplicates.has(value)) return 'Assigned to another function'
    return ''
  }, [catalog, reservedByPin, duplicates])

  const blocked = useMemo(
    () => Object.entries(draft).some(([field, value]) => !!localProblem(field, value)),
    [draft, localProblem],
  )

  const apply = useCallback(() => {
    actions.protect({
      label: 'Pin reassignment',
      run: async (fresh: string) => {
        try {
          const result = await api.updatePins(fresh, changed)
          setToken(fresh)
          setWarnings(result.warnings)
          setRestart(result.restart_command)
          setErrors([])
          actions.notify('Pin map written')
          await load(fresh)
        } catch (reason) {
          const message = reason instanceof Error ? reason.message : 'Pin change rejected'
          // The API returns a structured list when validation fails server-side.
          try {
            const parsed = JSON.parse(message)
            setErrors(parsed.errors ?? [message])
          } catch {
            setErrors([message])
          }
          throw reason
        }
      },
    })
  }, [actions, changed, load])

  if (!token) {
    return (
      <div className="network-locked">
        <CircuitBoard />
        <div>
          <strong>Pin configuration is operator-protected</strong>
          <small>These lines drive relays and read sensors.</small>
        </div>
        <button className="button button-secondary" onClick={unlock}>Unlock</button>
      </div>
    )
  }

  const actuatorsArmed = catalog?.actuators_enabled
  const hasChanges = Object.keys(changed).length > 0

  return (
    <div className="pin-editor">
      {!catalog?.editable && (
        <div className="pin-note">
          <Info size={15} />
          <span>
            {catalog?.config_path
              ? `Read-only here: pin edits are written to ${catalog.config_path} on a physical appliance.`
              : 'Pin editing is available on a physical appliance with /etc/aeroos/hardware.toml.'}
          </span>
        </div>
      )}

      {actuatorsArmed && (
        <div className="pin-note pin-note-warn">
          <ShieldAlert size={15} />
          <span>
            The actuator master enable is on. Turn it off before moving a relay line, so the old
            GPIO is released while the output is in a known-safe state.
          </span>
        </div>
      )}

      <div className="pin-grid">
        {catalog?.pins.map(pin => {
          const value = draft[pin.field]
          const problem = localProblem(pin.field, value)
          const dirty = value !== pin.value
          return (
            <label key={pin.field} className={`pin-row ${problem ? 'pin-bad' : ''} ${dirty ? 'pin-dirty' : ''}`}>
              <span className="pin-label">
                <strong>{pin.label}</strong>
                <small>
                  {pin.table}.{pin.key}
                  {pin.actuator && <em className="pin-actuator">relay</em>}
                </small>
              </span>
              <span className="pin-input">
                <span className="pin-prefix">BCM</span>
                <input
                  type="number"
                  inputMode="numeric"
                  min={catalog.range.min}
                  max={catalog.range.max}
                  value={Number.isNaN(value) ? '' : value}
                  disabled={!catalog.editable}
                  onChange={event => setDraft(current => ({ ...current, [pin.field]: parseInt(event.target.value, 10) }))}
                />
              </span>
              {problem
                ? <span className="pin-problem">{problem}</span>
                : dirty && <span className="pin-was">was BCM{pin.value}</span>}
            </label>
          )
        })}
      </div>

      {errors.length > 0 && (
        <div className="diag-error">
          <AlertTriangle size={15} />
          <ul>{errors.map(item => <li key={item}>{item}</li>)}</ul>
        </div>
      )}

      {warnings.length > 0 && (
        <div className="pin-note pin-note-warn">
          <AlertTriangle size={15} />
          <ul>{warnings.map(item => <li key={item}>{item}</li>)}</ul>
        </div>
      )}

      {restart && (
        <div className="pin-note">
          <Check size={15} />
          <span>Written. The control service builds its GPIO objects at start-up, so run <code>{restart}</code> to apply.</span>
        </div>
      )}

      <div className="pin-actions">
        <button
          className="button"
          disabled={!hasChanges}
          onClick={() => catalog && setDraft(Object.fromEntries(catalog.pins.map(pin => [pin.field, pin.value])))}
        >
          <RotateCcw size={15} />Revert
        </button>
        <button
          className="button button-primary"
          disabled={!hasChanges || blocked || !catalog?.editable}
          onClick={apply}
        >
          <Check size={15} />Apply {hasChanges ? `${Object.keys(changed).length} change${Object.keys(changed).length > 1 ? 's' : ''}` : ''}
        </button>
      </div>

      <details className="pin-reserved">
        <summary>Reserved lines ({catalog?.reserved.length ?? 0})</summary>
        <ul>
          {catalog?.reserved.map(entry => (
            <li key={entry.gpio}><code>BCM{entry.gpio}</code>{entry.reason}</li>
          ))}
        </ul>
      </details>
    </div>
  )
}
