// Chart tokens for autopilot SVG charts.
//
// SVG presentation attributes cannot consume Tailwind classes, so every color
// that lands inside an <svg> is sourced here as a raw value. Provenance:
//   MIST   -> the `mist` ramp in frontend/tailwind.config.js
//   SLATE  -> Tailwind default slate scale (already the app's surface scale)
//   CHART  -> severity ring values from utils/severity.js, mapped to roles
//
// Nothing in this file invents a color. Change the ramp in tailwind.config.js
// or the ring values in severity.js and mirror the change here.

import { SEVERITY_CONFIG } from './severity'

export const MIST = {
  50:  '#f0f7ff',
  100: '#e0effe',
  200: '#bae0fd',
  300: '#7cc8fb',
  400: '#36aaf5',
  500: '#0c8fe6',
  600: '#0071c4',
  700: '#015a9f',
  800: '#064d83',
  900: '#0b416d',
}

export const SLATE = {
  200: '#e2e8f0',
  300: '#cbd5e1',
  400: '#94a3b8',
  500: '#64748b',
  600: '#475569',
  700: '#334155',
  800: '#1e293b',
  900: '#0f172a',
  950: '#020617',
}

export const CHART = {
  entitledLine:       MIST[400],
  entitledFill:       MIST[500],
  entitledFillTop:    0.22,
  entitledFillBottom: 0.01,
  usageLine:          SEVERITY_CONFIG.warning.ring,
  breach:             SEVERITY_CONFIG.critical.ring,
  healthy:            SEVERITY_CONFIG.ok.ring,
  info:               SEVERITY_CONFIG.info.ring,
  grid:               SLATE[800],
  axis:               SLATE[700],
  tick:               SLATE[500],
  label:              SLATE[400],
  value:              SLATE[200],
  surface:            SLATE[900],
}

// Native Mist step-chart proportions, sized for the wide drill-down panel.
export const GEOMETRY = {
  width:  660,
  height: 240,
  margin: { top: 18, right: 74, bottom: 34, left: 46 },
}

export const DAY = 86400
export const YEAR = 365 * DAY

const MONTHS = [
  'JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN',
  'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC',
]

// All formatting is UTC to match the backend, which renders dd-MON-yyyy from
// UTC epochs in sub_monitor.py.
export function fmtDate(epoch) {
  if (epoch === null || epoch === undefined) return '—'
  const d = new Date(epoch * 1000)
  const day = String(d.getUTCDate()).padStart(2, '0')
  return `${day}-${MONTHS[d.getUTCMonth()]}-${d.getUTCFullYear()}`
}

export function fmtMonth(epoch) {
  const d = new Date(epoch * 1000)
  return `${MONTHS[d.getUTCMonth()]} '${String(d.getUTCFullYear()).slice(2)}`
}

export function daysUntil(epoch, from) {
  return Math.floor((epoch - from) / DAY)
}

// Month-boundary ticks across [start, end], thinned so labels never collide.
export function monthTicks(start, end, maxTicks = 10) {
  if (!(end > start)) return []
  const s = new Date(start * 1000)
  const e = new Date(end * 1000)
  const span =
    (e.getUTCFullYear() - s.getUTCFullYear()) * 12 +
    (e.getUTCMonth() - s.getUTCMonth())
  const step = Math.max(1, Math.ceil(span / maxTicks))

  const ticks = []
  let y = s.getUTCFullYear()
  let m = s.getUTCMonth() + 1
  for (;;) {
    const t = Math.floor(Date.UTC(y, m, 1) / 1000)
    if (t > end) break
    ticks.push(t)
    m += step
    while (m > 11) {
      m -= 12
      y += 1
    }
  }
  return ticks
}

// Zero-based y axis with a readable top value and evenly spaced ticks.
export function niceScale(maxValue, tickCount = 4) {
  const target = Math.max(1, maxValue)
  const rough = target / tickCount
  const mag = Math.pow(10, Math.floor(Math.log10(rough)))
  const norm = rough / mag
  const stepMult = norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10
  const step = stepMult * mag
  const top = Math.ceil(target / step) * step
  const ticks = []
  for (let v = 0; v <= top + 1e-9; v += step) ticks.push(Math.round(v))
  return { top, ticks }
}
