// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AppShell, Overview } from './App'
import type { DashboardData } from './types'

afterEach(cleanup)

const data: DashboardData = {
  status: {
    state: 'safe', reason: 'Nominal', commissioned: true, automation_enabled: true, simulator: true,
    active_experiment: 'Mint airflow study', pump_active: false, dosing_active: false,
    fan_requested: false, fan_active: false, actuators_enabled: true,
    hardware_capabilities: {
      climate: true, solution_temperature: true, light: true, camera: true,
      reservoir_level: true, flow: true, ph: true, ec: true, mist_output: true,
      fan_output: true, nutrient_dosing: true, mixer: true,
    },
    missing_interlocks: [], development_session_expires_at: null,
    next_spray_at: new Date(Date.now() + 300_000).toISOString(), last_successful_spray_at: null,
    open_alerts: 0, version: '0.1.0', timestamp: new Date().toISOString(),
  },
  sensors: {
    timestamp: new Date().toISOString(), air_temperature_c: 25.4, relative_humidity_percent: 81,
    light_lux: 6400, light_percent: 54, solution_temperature_c: 21.2, ph: 6.1, ec_ms_cm: 1.72,
    reservoir_percent: 76, flow_lpm: 0, power_voltage: 12.1, battery_percent: 94,
  },
  history: [], alerts: [], experiments: [], captures: [],
  identity: { product: 'AeroOS', edition: 'Research Preview', version: '0.1.0', hostname: 'aeroos.local', hardware: 'Simulator', kernel: 'host', chamber_name: 'Research chamber A1' },
}

function renderShell(overrides: Partial<DashboardData> = {}) {
  const protect = vi.fn()
  const setTheme = vi.fn()
  const merged = { ...data, ...overrides }
  render(
    <MemoryRouter initialEntries={['/']}>
      <AppShell data={merged} theme="light" setTheme={setTheme} actions={{ protect, refresh: vi.fn(), notify: vi.fn(), token: null }}>
        <div>Dashboard content</div>
      </AppShell>
    </MemoryRouter>,
  )
  return { protect, setTheme }
}

describe('AeroOS production shell', () => {
  it('opens the app launcher and navigates through existing workspaces', () => {
    renderShell()
    fireEvent.click(screen.getByRole('button', { name: 'Open app launcher' }))
    const launcher = screen.getByRole('dialog', { name: 'Applications' })
    fireEvent.click(within(launcher).getByRole('button', { name: 'Nutrients' }))
    expect(screen.queryByRole('dialog', { name: 'Applications' })).not.toBeInTheDocument()
    expect(screen.getByText('Nutrients')).toBeInTheDocument()
  })

  it('keeps sheets exclusive, closes with Escape, and restores focus', () => {
    renderShell()
    const apps = screen.getByRole('button', { name: 'Open app launcher' })
    fireEvent.click(apps)
    expect(screen.getByRole('dialog', { name: 'Applications' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Open system controls' }))
    expect(screen.queryByRole('dialog', { name: 'Applications' })).not.toBeInTheDocument()
    expect(screen.getByRole('dialog', { name: 'System' })).toBeInTheDocument()
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByRole('dialog', { name: 'System' })).not.toBeInTheDocument()
  })

  it('persists the theme choice through the shell callback', () => {
    const { setTheme } = renderShell()
    fireEvent.click(screen.getByRole('button', { name: 'Use dark theme' }))
    expect(setTheme).toHaveBeenCalledWith('dark')
  })

  it('routes misting through protected authorization', () => {
    const { protect } = renderShell()
    fireEvent.click(screen.getByRole('button', { name: 'Open mist controls' }))
    fireEvent.click(screen.getByRole('button', { name: 'Authorize safe mist' }))
    expect(protect).toHaveBeenCalledTimes(1)
    expect(protect.mock.calls[0][0]).toMatchObject({ label: 'Start misting' })
    expect(protect.mock.calls[0][0].run).toBeTypeOf('function')
    expect(screen.queryByRole('dialog', { name: 'Mist control' })).not.toBeInTheDocument()
  })

  it('uses a PIN-protected switch for automatic recirculation', () => {
    const { protect } = renderShell()
    fireEvent.click(screen.getByRole('button', { name: 'Open mist controls' }))
    const automatic = screen.getByRole('switch', { name: 'Disable automatic recirculation' })
    expect(automatic).toHaveAttribute('aria-checked', 'true')
    fireEvent.click(automatic)
    expect(protect).toHaveBeenCalledTimes(1)
    expect(protect.mock.calls[0][0]).toMatchObject({ label: 'Disable automatic recirculation' })
    expect(protect.mock.calls[0][0].run).toBeTypeOf('function')
  })

  it('does not let the interface toggle bypass an uncommissioned relay output', () => {
    renderShell({ status: { ...data.status!, automation_enabled: false, actuators_enabled: false } })
    fireEvent.click(screen.getByRole('button', { name: 'Open mist controls' }))
    expect(screen.getByRole('switch', { name: 'Enable automatic recirculation' })).toBeDisabled()
    expect(screen.getByText('Commission and verify the relay output first')).toBeInTheDocument()
  })

  it('disables unsafe misting during a critical lockout', () => {
    renderShell({ status: { ...data.status!, state: 'critical', reason: 'Flow verification failed' } })
    expect(screen.getByRole('alert')).toHaveTextContent('Critical lockout')
    fireEvent.click(screen.getByRole('button', { name: 'Open mist controls' }))
    expect(screen.getByRole('button', { name: 'Locked by safety engine' })).toBeDisabled()
  })
})

describe('AeroOS home dashboard', () => {
  it('collapses and restores the hardware health panel', () => {
    const actions = { protect: vi.fn(), refresh: vi.fn(), notify: vi.fn(), token: null }
    render(<MemoryRouter><Overview data={data} actions={actions} /></MemoryRouter>)

    expect(screen.getByRole('complementary', { name: 'Connected hardware' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Collapse hardware panel' }))
    expect(screen.queryByRole('complementary', { name: 'Connected hardware' })).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Open hardware panel' }))
    expect(screen.getByRole('complementary', { name: 'Connected hardware' })).toBeInTheDocument()
  })
})
