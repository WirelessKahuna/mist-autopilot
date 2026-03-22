import React from 'react'
import ScoreRing from './ScoreRing'
import { getSeverityConfig } from '../utils/severity'

function scoreToSeverity(score) {
  if (score === null || score === undefined) return 'unavailable'
  if (score >= 80) return 'ok'
  if (score >= 60) return 'info'
  if (score >= 40) return 'warning'
  return 'critical'
}

export default function OrgHeader({ org, onRefresh, loading, lastUpdated }) {
  const severity = scoreToSeverity(org?.overall_score)
  const cfg = getSeverityConfig(severity)

  return (
    <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-6 mb-8">
      {/* Left — branding + org info */}
      <div className="flex items-center gap-4">
        <div className="flex flex-col gap-1">
          <div className="flex items-center gap-2">
            <span className="text-xl font-semibold text-white tracking-tight">Mist Autopilot</span>
            <span className="text-xs text-slate-500 font-medium px-2 py-0.5 bg-slate-800 rounded-full border border-slate-700">
              Self-Driving Network Review
            </span>
          </div>
          {org && (
            <div className="flex items-center gap-3 text-sm text-slate-400">
              <span className="font-medium text-slate-200">{org.org_name}</span>
              <span className="text-slate-600">·</span>
              <span>{org.site_count} sites</span>
              {lastUpdated && (
                <>
                  <span className="text-slate-600">·</span>
                  <span>Updated {lastUpdated}</span>
                </>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Right — overall score + refresh */}
      <div className="flex items-center gap-5">
        {org?.overall_score !== undefined && (
          <div className="flex items-center gap-3">
            <ScoreRing score={org.overall_score} severity={severity} size={72} />
            <div>
              <p className="text-xs text-slate-500 mb-0.5">Org Health</p>
              <p className={`text-sm font-semibold ${cfg.text}`}>{cfg.label}</p>
            </div>
          </div>
        )}
        <button
          onClick={onRefresh}
          disabled={loading}
          className="flex items-center gap-2 px-4 py-2 rounded-lg bg-mist-600 hover:bg-mist-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium transition-colors"
        >
          <span className={loading ? 'animate-spin inline-block' : ''}>↻</span>
          {loading ? 'Scanning…' : 'Refresh All'}
        </button>
      </div>
    </div>
  )
}
