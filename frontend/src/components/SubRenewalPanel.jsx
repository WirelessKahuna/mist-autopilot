import React, { useMemo, useState } from 'react'
import { getSeverityConfig } from '../utils/severity'
import {
  CHART,
  GEOMETRY,
  DAY,
  YEAR,
  fmtDate,
  fmtMonth,
  daysUntil,
  monthTicks,
  niceScale,
} from '../utils/chartTokens'

// SubRenewalPanel renders the structured payload emitted by the SUBMonitor v2
// backend module (ModuleOutput.data). Contract, from backend/modules/sub_monitor.py:
//
//   as_of       : int, UTC epoch seconds at scan time
//   skus        : { [sku]: { label, entitled, usage, fully_loaded, status,
//                            timeline: [{ t, allowed }],
//                            drops: [{ t, date, qty_expiring, allowed_after,
//                                      orders: [], shortfall }] } }
//   orders      : [ { order_id, class, lines: [{ subscription_id, sku, label,
//                                                qty, start, end }] } ]
//   paired_skus : [ [skuA, skuB], ... ]
//   evals       : { [kind]: count }
//
// No field is read that is not in that contract.

const STATUS_META = {
  exceeded: { severity: 'critical', label: 'Exceeded' },
  active:   { severity: 'ok',       label: 'Active' },
  inactive: { severity: 'unavailable', label: 'Not entitled' },
}

const CLASS_META = {
  production:   { label: 'Production', cls: 'bg-mist-500/10 text-mist-300 border-mist-500/30' },
  system_grant: { label: 'Mist grant', cls: 'bg-slate-500/10 text-slate-400 border-slate-600' },
  eval:         { label: 'Evaluation', cls: 'bg-amber-500/10 text-amber-400 border-amber-500/30' },
}

const ORDER_ALIAS = { Mist: 'eval', '00000000': 'Mist grant' }

function orderLabel(orderId) {
  return ORDER_ALIAS[orderId] || orderId
}

// ---------------------------------------------------------------------------
// Status strip
// ---------------------------------------------------------------------------

function StatusRow({ sku, payload, asOf, pairedWith }) {
  const meta = STATUS_META[payload.status] || STATUS_META.inactive
  const cfg = getSeverityConfig(meta.severity)

  const nextDrop = (payload.drops || []).find(d => d.t > asOf)
  const firstBreach = (payload.drops || []).find(d => d.shortfall > 0)

  return (
    <div className="flex items-start justify-between gap-3 py-2.5 border-b border-slate-800 last:border-0">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className={`w-2 h-2 rounded-full shrink-0 ${cfg.dot}`} />
          <span className="text-sm text-slate-200 truncate">{payload.label}</span>
          <span className="text-xs text-slate-500 font-mono shrink-0">{sku}</span>
          {pairedWith && (
            <span
              className="text-xs text-slate-600 font-mono shrink-0"
              title={`Paired order line with ${pairedWith}`}
            >
              +{pairedWith}
            </span>
          )}
        </div>
        <p className="text-xs text-slate-500 mt-1 ml-4">
          {nextDrop
            ? `Next expiry ${nextDrop.date}, ${nextDrop.qty_expiring} unit(s), entitlement drops to ${nextDrop.allowed_after}`
            : 'No scheduled expiry'}
          {firstBreach && (
            <span className="text-red-400">
              {` · shortfall ${firstBreach.shortfall} on ${firstBreach.date}`}
            </span>
          )}
        </p>
      </div>
      <div className="text-right shrink-0">
        <p className="text-sm font-semibold text-slate-100 font-mono">
          {payload.usage} / {payload.entitled}
        </p>
        <span className={`text-xs px-2 py-0.5 rounded-full ${cfg.bg} ${cfg.text}`}>
          {meta.label}
        </span>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Step chart, native Mist structure on the autopilot dark skin
// ---------------------------------------------------------------------------

function TimelineChart({ payload, asOf }) {
  const series = payload.timeline || []
  if (series.length === 0) return null

  const { width, height, margin } = GEOMETRY
  const innerW = width - margin.left - margin.right
  const innerH = height - margin.top - margin.bottom

  const lastT = series[series.length - 1].t
  const tStart = asOf
  const tEnd =
    lastT > asOf
      ? lastT + Math.max(20 * DAY, (lastT - asOf) * 0.06)
      : asOf + YEAR

  const usage = payload.usage || 0
  const maxVal = Math.max(usage, ...series.map(p => p.allowed))
  const { top, ticks: yTicks } = niceScale(maxVal)

  const x = t => margin.left + ((t - tStart) / (tEnd - tStart)) * innerW
  const y = v => margin.top + innerH - (v / top) * innerH

  // Step path: hold each level until the next event, then step vertically.
  const stepCmds = []
  stepCmds.push(`M ${x(series[0].t)} ${y(series[0].allowed)}`)
  for (let i = 1; i < series.length; i++) {
    stepCmds.push(`L ${x(series[i].t)} ${y(series[i - 1].allowed)}`)
    stepCmds.push(`L ${x(series[i].t)} ${y(series[i].allowed)}`)
  }
  stepCmds.push(`L ${x(tEnd)} ${y(series[series.length - 1].allowed)}`)
  const linePath = stepCmds.join(' ')
  const areaPath =
    `${linePath} L ${x(tEnd)} ${y(0)} L ${x(series[0].t)} ${y(0)} Z`

  const xTicks = monthTicks(tStart, tEnd)
  const breaches = (payload.drops || []).filter(d => d.shortfall > 0 && d.t <= tEnd)
  const gradientId = `entitled-fill-${payload.label.replace(/[^a-zA-Z0-9]/g, '')}`

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900 p-3">
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full h-auto" role="img">
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={CHART.entitledFill} stopOpacity={CHART.entitledFillTop} />
            <stop offset="100%" stopColor={CHART.entitledFill} stopOpacity={CHART.entitledFillBottom} />
          </linearGradient>
        </defs>

        {/* Horizontal grid and y ticks, zero-based */}
        {yTicks.map(v => (
          <g key={`y-${v}`}>
            <line
              x1={margin.left} x2={width - margin.right}
              y1={y(v)} y2={y(v)}
              stroke={CHART.grid} strokeWidth="1"
            />
            <text
              x={margin.left - 8} y={y(v) + 3}
              textAnchor="end" fontSize="10" fill={CHART.tick}
            >
              {v}
            </text>
          </g>
        ))}

        {/* Month ticks */}
        {xTicks.map(t => (
          <g key={`x-${t}`}>
            <line
              x1={x(t)} x2={x(t)}
              y1={margin.top} y2={margin.top + innerH}
              stroke={CHART.grid} strokeWidth="1" strokeDasharray="2 4"
            />
            <text
              x={x(t)} y={height - margin.bottom + 15}
              textAnchor="middle" fontSize="10" fill={CHART.tick}
            >
              {fmtMonth(t)}
            </text>
          </g>
        ))}

        {/* Entitled level */}
        <path d={areaPath} fill={`url(#${gradientId})`} />
        <path
          d={linePath}
          fill="none"
          stroke={CHART.entitledLine}
          strokeWidth="2"
          strokeLinejoin="miter"
        />

        {/* Current usage, dashed, labeled at the right edge */}
        <line
          x1={margin.left} x2={width - margin.right}
          y1={y(usage)} y2={y(usage)}
          stroke={CHART.usageLine} strokeWidth="1.5" strokeDasharray="5 4"
        />
        <text
          x={width - margin.right + 6} y={y(usage) + 3}
          fontSize="10" fill={CHART.usageLine}
        >
          usage {usage}
        </text>

        {/* Breach events */}
        {breaches.map(d => (
          <g key={`b-${d.t}`}>
            <line
              x1={x(d.t)} x2={x(d.t)}
              y1={margin.top} y2={margin.top + innerH}
              stroke={CHART.breach} strokeWidth="1" strokeDasharray="3 3" opacity="0.7"
            />
            <circle cx={x(d.t)} cy={y(d.allowed_after)} r="3.5" fill={CHART.breach} />
          </g>
        ))}

        {/* Axes */}
        <line
          x1={margin.left} x2={width - margin.right}
          y1={margin.top + innerH} y2={margin.top + innerH}
          stroke={CHART.axis} strokeWidth="1"
        />
        <line
          x1={margin.left} x2={margin.left}
          y1={margin.top} y2={margin.top + innerH}
          stroke={CHART.axis} strokeWidth="1"
        />
      </svg>

      <div className="flex items-center gap-4 mt-2 pl-1">
        <span className="flex items-center gap-1.5 text-xs text-slate-400">
          <span className="w-3 h-0.5" style={{ backgroundColor: CHART.entitledLine }} />
          Entitled
        </span>
        <span className="flex items-center gap-1.5 text-xs text-slate-400">
          <span
            className="w-3 h-0"
            style={{ borderTop: `2px dashed ${CHART.usageLine}` }}
          />
          Current usage
        </span>
        {breaches.length > 0 && (
          <span className="flex items-center gap-1.5 text-xs text-slate-400">
            <span
              className="w-2 h-2 rounded-full"
              style={{ backgroundColor: CHART.breach }}
            />
            Coverage breach
          </span>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Order table
// ---------------------------------------------------------------------------

// Roll known paired SKUs (identical qty and dates within one order) onto a
// single display row. paired_skus is supplied by the backend.
function rollUpLines(lines, pairs) {
  const remaining = [...lines]
  const rows = []
  while (remaining.length) {
    const line = remaining.shift()
    const partnerSku = pairs
      .filter(p => p.includes(line.sku))
      .map(p => (p[0] === line.sku ? p[1] : p[0]))
      .find(sku =>
        remaining.some(
          l => l.sku === sku && l.qty === line.qty && l.start === line.start && l.end === line.end
        )
      )
    if (partnerSku) {
      const idx = remaining.findIndex(
        l => l.sku === partnerSku && l.qty === line.qty && l.start === line.start && l.end === line.end
      )
      const partner = remaining.splice(idx, 1)[0]
      rows.push({
        key: `${line.subscription_id}+${partner.subscription_id}`,
        skus: [line.sku, partner.sku],
        label: `${line.label} + ${partner.label}`,
        qty: line.qty,
        start: line.start,
        end: line.end,
      })
    } else {
      rows.push({
        key: line.subscription_id || `${line.sku}-${line.start}`,
        skus: [line.sku],
        label: line.label,
        qty: line.qty,
        start: line.start,
        end: line.end,
      })
    }
  }
  return rows
}

function OrderCard({ order, pairs, asOf }) {
  const meta = CLASS_META[order.class] || CLASS_META.production
  const rows = rollUpLines(order.lines || [], pairs)
  const earliestEnd = Math.min(...rows.map(r => r.end || Infinity))
  const expired = earliestEnd < asOf

  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900 p-3">
      <div className="flex items-center justify-between gap-2 mb-2">
        <span className="text-xs font-mono text-slate-300">{orderLabel(order.order_id)}</span>
        <div className="flex items-center gap-2">
          {expired && (
            <span className="text-xs text-slate-600">expired</span>
          )}
          <span className={`text-xs px-2 py-0.5 rounded-full border ${meta.cls}`}>
            {meta.label}
          </span>
        </div>
      </div>
      <div className="space-y-1">
        {rows.map(r => {
          const days = r.end ? daysUntil(r.end, asOf) : null
          return (
            <div key={r.key} className="flex items-center justify-between gap-3 text-xs">
              <div className="min-w-0 flex items-center gap-2">
                <span className="font-mono text-slate-500 shrink-0">{r.skus.join(' + ')}</span>
                <span className="text-slate-400 truncate">{r.label}</span>
              </div>
              <div className="flex items-center gap-3 shrink-0 font-mono">
                <span className="text-slate-300">{r.qty}</span>
                <span className={days !== null && days < 0 ? 'text-slate-600' : 'text-slate-400'}>
                  {fmtDate(r.end)}
                </span>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Panel
// ---------------------------------------------------------------------------

export default function SubRenewalPanel({ data }) {
  const [showTimeline, setShowTimeline] = useState(false)
  const [showAllOrders, setShowAllOrders] = useState(false)
  const [selectedSku, setSelectedSku] = useState(null)

  const asOf = data?.as_of
  const skus = data?.skus || {}
  const orders = data?.orders || []
  const pairs = data?.paired_skus || []

  const pairedWith = useMemo(() => {
    const map = {}
    pairs.forEach(([a, b]) => {
      if (skus[a] && skus[b]) {
        map[a] = b
        map[b] = a
      }
    })
    return map
  }, [pairs, skus])

  const rank = { exceeded: 0, active: 1, inactive: 2 }
  const skuKeys = Object.keys(skus).sort(
    (a, b) =>
      (rank[skus[a].status] ?? 3) - (rank[skus[b].status] ?? 3) ||
      a.localeCompare(b)
  )

  const chartable = skuKeys.filter(s => (skus[s].timeline || []).length > 0)
  const activeSku =
    selectedSku && skus[selectedSku] ? selectedSku : chartable[0] || null

  if (skuKeys.length === 0) {
    return (
      <section>
        <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-3">
          Subscriptions
        </h3>
        <p className="text-sm text-slate-500">No subscription data returned for this org.</p>
      </section>
    )
  }

  const visibleOrders = showAllOrders ? orders : orders.slice(0, 5)

  return (
    <div className="space-y-7">
      {/* Status strip */}
      <section>
        <div className="flex items-baseline justify-between mb-3">
          <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
            Subscription status
          </h3>
          {asOf && (
            <span className="text-xs text-slate-600 font-mono">as of {fmtDate(asOf)}</span>
          )}
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-900 px-4 py-1">
          {skuKeys.map(sku => (
            <StatusRow
              key={sku}
              sku={sku}
              payload={skus[sku]}
              asOf={asOf}
              pairedWith={pairedWith[sku]}
            />
          ))}
        </div>
      </section>

      {/* Renewal timeline */}
      {chartable.length > 0 && (
        <section>
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
              Renewal timeline
            </h3>
            <button
              onClick={() => setShowTimeline(v => !v)}
              className="px-3 py-1.5 rounded-md bg-mist-600 hover:bg-mist-500 text-white text-xs font-medium transition-colors"
            >
              {showTimeline ? 'Hide timeline' : 'Show timeline'}
            </button>
          </div>

          {showTimeline && activeSku && (
            <div className="space-y-3">
              <div className="flex flex-wrap gap-1.5">
                {chartable.map(sku => (
                  <button
                    key={sku}
                    onClick={() => setSelectedSku(sku)}
                    className={`px-2.5 py-1 rounded-md text-xs font-mono transition-colors ${
                      sku === activeSku
                        ? 'bg-mist-600 text-white'
                        : 'bg-slate-800 text-slate-400 hover:text-slate-200'
                    }`}
                  >
                    {sku}
                  </button>
                ))}
              </div>

              <p className="text-xs text-slate-400">
                {skus[activeSku].label}: {skus[activeSku].usage} in use against{' '}
                {skus[activeSku].entitled} entitled, worst case demand{' '}
                {skus[activeSku].fully_loaded}.
              </p>

              <TimelineChart payload={skus[activeSku]} asOf={asOf} />
            </div>
          )}
        </section>
      )}

      {/* Order table */}
      {orders.length > 0 && (
        <section>
          <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-3">
            Orders ({orders.length}), earliest expiry first
          </h3>
          <div className="space-y-2">
            {visibleOrders.map(o => (
              <OrderCard key={o.order_id} order={o} pairs={pairs} asOf={asOf} />
            ))}
          </div>
          {orders.length > 5 && (
            <button
              onClick={() => setShowAllOrders(v => !v)}
              className="mt-2 text-xs text-mist-400 hover:text-mist-300 transition-colors"
            >
              {showAllOrders ? 'Show fewer' : `Show all ${orders.length} orders`}
            </button>
          )}
        </section>
      )}
    </div>
  )
}
