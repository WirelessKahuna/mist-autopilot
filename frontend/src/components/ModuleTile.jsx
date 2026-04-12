import React, { useState } from 'react'
import ScoreRing from './ScoreRing'
import { getSeverityConfig } from '../utils/severity'
import { runModule } from '../api/client'

export default function ModuleTile({ module, onDrillDown }) {
  const [refreshing, setRefreshing] = useState(false)
  const [data, setData] = useState(module)

  const cfg = getSeverityConfig(data.severity)
  const isComingSoon = data.status === 'coming_soon'
  const isError = data.status === 'error'

  async function handleRefresh(e) {
    e.stopPropagation()
    setRefreshing(true)
    try {
      const updated = await runModule(data.module_id)
      setData(updated)
    } catch (_) {}
    setRefreshing(false)
  }

  return (
    <div
      onClick={() => !isComingSoon && onDrillDown(data)}
      className={`
        relative rounded-xl border p-5 flex flex-col gap-4 transition-all duration-200
        ${cfg.border} bg-slate-900
        ${isComingSoon
          ? 'opacity-50 cursor-default'
          : 'cursor-pointer hover:bg-slate-800 hover:scale-[1.01]'}
      `}
    >
      {/* Header */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className="text-2xl">{data.icon}</span>
          <div>
            <p className="text-sm font-medium text-slate-100 leading-tight">{data.display_name}</p>
            <span className={`text-xs font-medium px-2 py-0.5 rounded-full mt-1 inline-block ${cfg.bg} ${cfg.text}`}>
              {cfg.label}
            </span>
          </div>
        </div>
        <ScoreRing score={data.score} severity={data.severity} size={64} />
      </div>

      {/* Summary */}
      <p className={`text-xs leading-relaxed flex-grow ${isComingSoon ? 'text-slate-600' : 'text-slate-300'}`}>
        {isError ? `⚠ ${data.error}` : data.summary}
      </p>

      {/* Finding count badges — pushed to bottom above footer */}
      {!isComingSoon && !isError && data.findings?.length > 0 && (
        <div className="flex flex-wrap gap-2 mt-auto">
          {['critical', 'warning', 'info'].map(sev => {
            const count = data.findings.filter(f => f.severity === sev).length
            if (!count) return null
            const c = getSeverityConfig(sev)
            return (
              <span key={sev} className={`text-xs px-2 py-0.5 rounded-full ${c.bg} ${c.text}`}>
                {count} {sev}
              </span>
            )
          })}
        </div>
      )}

      {/* Footer */}
      <div className="flex items-center justify-between pt-2 border-t border-slate-800">
        {isComingSoon ? (
          <span className="text-xs text-slate-600">In development</span>
        ) : (
          <span className="text-xs text-slate-500">
            {data.sites?.length > 0 ? `${data.sites.length} sites analyzed` : 'Org-level analysis'}
          </span>
        )}
        {!isComingSoon && (
          <button
            onClick={handleRefresh}
            disabled={refreshing}
            className="text-xs text-slate-500 hover:text-slate-300 transition-colors disabled:opacity-40"
          >
            {refreshing ? 'Refreshing…' : '↻ Refresh'}
          </button>
        )}
      </div>
    </div>
  )
}
