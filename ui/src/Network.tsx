import { FormEvent, useCallback, useEffect, useState } from 'react'
import { AlertTriangle, Check, Globe, Loader2, Lock, RefreshCw, Wifi, WifiOff, X } from 'lucide-react'
import { api } from './api'
import type { NetworkStatus, WifiNetwork } from './types'

type Actions = {
  protect: (action: { label: string, run: (token: string) => Promise<unknown> }) => void
  notify: (message: string, tone?: 'success' | 'warning') => void
}

function SignalBars({ strength }: { strength: number }) {
  return (
    <span className="signal-bars" aria-label={`Signal ${strength} of 4`}>
      {[1, 2, 3, 4].map(level => (
        <i key={level} className={level <= strength ? 'on' : ''} style={{ height: `${4 + level * 3}px` }} />
      ))}
    </span>
  )
}

function JoinDialog({ network, onClose, onJoin }: {
  network: WifiNetwork
  onClose: () => void
  onJoin: (passphrase: string | null) => Promise<void>
}) {
  const [passphrase, setPassphrase] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const open = network.security === 'open'

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      await onJoin(open ? null : passphrase)
      // Never keep the credential in component state once it has been handed off.
      setPassphrase('')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not join the network')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="dialog-backdrop" role="presentation" onMouseDown={event => event.target === event.currentTarget && onClose()}>
      <div className="dialog" role="dialog" aria-modal="true" aria-labelledby="join-title">
        <button className="icon-button dialog-close" onClick={onClose} aria-label="Close"><X /></button>
        <span className="dialog-icon"><Wifi /></span>
        <span className="eyebrow">Join network</span>
        <h2 id="join-title">{network.ssid}</h2>
        <p>
          {open
            ? 'This network is unencrypted. Anything the appliance sends is visible on the air.'
            : 'The passphrase is handed to iwd and stored by it. AeroOS does not keep or log it.'}
        </p>
        <form onSubmit={submit}>
          {!open && (
            <label>
              Passphrase
              <input
                autoFocus
                type="password"
                autoComplete="off"
                value={passphrase}
                minLength={8}
                onChange={event => setPassphrase(event.target.value)}
                placeholder="Network passphrase"
              />
            </label>
          )}
          {error && <p className="form-error">{error}</p>}
          <button className="button button-primary button-wide" disabled={busy || (!open && passphrase.length < 8)}>
            {busy ? <><Loader2 className="spin" />Joining…</> : <><Check />Join network</>}
          </button>
        </form>
      </div>
    </div>
  )
}

export default function NetworkPanel({ actions }: { actions: Actions }) {
  const [token, setToken] = useState<string | null>(() => sessionStorage.getItem('aeroos-token'))
  const [status, setStatus] = useState<NetworkStatus | null>(null)
  const [networks, setNetworks] = useState<WifiNetwork[]>([])
  const [scanning, setScanning] = useState(false)
  const [joining, setJoining] = useState<WifiNetwork | null>(null)
  const [error, setError] = useState('')

  const unlock = useCallback(() => {
    actions.protect({ label: 'Network settings', run: async (fresh: string) => { setToken(fresh) } })
  }, [actions])

  const refresh = useCallback(async (active: string) => {
    try {
      setStatus(await api.networkStatus(active))
      setError('')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Network status unavailable')
    }
  }, [])

  useEffect(() => { if (token) refresh(token) }, [token, refresh])

  const scan = useCallback(async () => {
    if (!token) { unlock(); return }
    setScanning(true)
    setError('')
    try {
      setNetworks(await api.wifiScan(token))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Scan failed')
    } finally {
      setScanning(false)
    }
  }, [token, unlock])

  const join = useCallback(async (network: WifiNetwork, passphrase: string | null) => {
    // Joining is elevation-gated, so route it through the PIN flow rather than
    // reusing a token that may be past its window.
    if (!token) { unlock(); return }
    await api.wifiConnect(token, network.ssid, passphrase)
    actions.notify(`Joined ${network.ssid}`)
    setJoining(null)
    await refresh(token)
    await scan()
  }, [token, unlock, actions, refresh, scan])

  const toggleLan = useCallback((enabled: boolean) => {
    actions.protect({
      label: enabled ? 'Publish API on the network' : 'Restrict API to the appliance',
      run: async (fresh: string) => {
        const result = await api.setLanExposure(fresh, enabled)
        setToken(fresh)
        await refresh(fresh)
        actions.notify(
          enabled
            ? `API will listen on the LAN after: ${result.restart_command}`
            : `API returns to loopback after: ${result.restart_command}`,
          'warning',
        )
      },
    })
  }, [actions, refresh])

  const forget = useCallback((ssid: string) => {
    actions.protect({
      label: `Forget ${ssid}`,
      run: async (fresh: string) => {
        await api.wifiForget(fresh, ssid)
        setToken(fresh)
        await scan()
      },
    })
  }, [actions, scan])

  if (!token) {
    return (
      <div className="network-locked">
        <WifiOff />
        <div>
          <strong>Network settings are operator-protected</strong>
          <small>Joining a network changes what this appliance can reach.</small>
        </div>
        <button className="button button-secondary" onClick={unlock}>Unlock</button>
      </div>
    )
  }

  return (
    <div className="network-panel">
      <div className="network-status">
        <span className={`network-icon ${status?.state === 'connected' ? 'online' : 'offline'}`}>
          {status?.state === 'connected' ? <Wifi /> : <WifiOff />}
        </span>
        <div className="network-status-text">
          <strong>{status?.ssid || (status?.available ? 'Not connected' : 'WiFi unavailable')}</strong>
          <small>
            {status?.address ? `${status.address} · ${status.interface}` : status?.detail || status?.interface}
            {status?.simulated && ' · simulated'}
          </small>
        </div>
        <button className="button button-secondary" onClick={scan} disabled={scanning}>
          {scanning ? <Loader2 className="spin" size={15} /> : <RefreshCw size={15} />}
          {scanning ? 'Scanning…' : 'Scan'}
        </button>
      </div>

      {error && <div className="diag-error"><AlertTriangle size={15} />{error}</div>}

      {networks.length > 0 && (
        <ul className="wifi-list">
          {networks.map(network => (
            <li key={network.ssid} className={network.connected ? 'wifi-connected' : ''}>
              <SignalBars strength={network.signal} />
              <span className="wifi-name">
                <strong>{network.ssid}</strong>
                <small>
                  {network.security === 'open' ? 'Open — unencrypted' : 'WPA2 personal'}
                  {network.known && ' · saved'}
                </small>
              </span>
              {network.security !== 'open' && <Lock size={13} className="wifi-lock" />}
              {network.connected
                ? <span className="wifi-badge"><Check size={12} />Connected</span>
                : <button className="button button-secondary" onClick={() => setJoining(network)}>Join</button>}
              {network.known && !network.connected && (
                <button className="link-button" onClick={() => forget(network.ssid)}>Forget</button>
              )}
            </li>
          ))}
        </ul>
      )}

      <div className="lan-exposure">
        <span className="lan-icon"><Globe size={17} /></span>
        <div className="lan-text">
          <strong>Reach the dashboard from other devices</strong>
          <small>
            The control API listens on loopback so only this touchscreen can reach it. Turning this
            on publishes misting, dosing, and the camera feed to everyone on the WiFi. The operator
            PIN is the only thing protecting them.
          </small>
        </div>
        <button
          className={`toggle ${status?.api_on_lan ? 'toggle-on' : ''}`}
          role="switch"
          aria-checked={!!status?.api_on_lan}
          aria-label="Publish the API on the local network"
          onClick={() => toggleLan(!status?.api_on_lan)}
        >
          <i />
        </button>
      </div>
      {status?.api_on_lan && (
        <div className="lan-warning">
          <AlertTriangle size={15} />
          <span>
            Published on the LAN. Applies after <code>sudo systemctl restart aeroos</code>. Currently
            bound to <code>{status.api_bind_host}</code>.
          </span>
        </div>
      )}

      {joining && (
        <JoinDialog
          network={joining}
          onClose={() => setJoining(null)}
          onJoin={passphrase => join(joining, passphrase)}
        />
      )}
    </div>
  )
}
