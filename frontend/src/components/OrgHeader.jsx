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

export default function OrgHeader({ org, onRefresh, loading, lastUpdated, apiStats, onOpenCredentials }) {
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
          <div className="flex items-center gap-3 text-sm text-slate-400">
            {/* Org name pill — always visible, always clickable */}
            <button
              onClick={onOpenCredentials}
              className="flex items-center gap-1.5 font-medium text-slate-200 hover:text-white bg-slate-800 hover:bg-slate-700 border border-slate-700 hover:border-slate-500 rounded-lg px-3 py-1 transition-all text-sm"
            >
              <span>{org ? org.org_name : 'Connect Org'}</span>
              <span className="text-slate-500 text-xs">{org ? '⇄' : '→'}</span>
            </button>
            {org && (
              <>
                <span className="text-slate-600">·</span>
                <span>{org.site_count} sites</span>
              </>
            )}
            {lastUpdated && (
              <>
                <span className="text-slate-600">·</span>
                <span>Updated {lastUpdated}</span>
              </>
            )}
            {apiStats && (
              <>
                <span className="text-slate-600">·</span>
                <span className="text-slate-500">
                  API Calls — Last:&nbsp;
                  <span className="text-slate-300">{apiStats.last_refresh}</span>
                  &nbsp;·&nbsp;Hour:&nbsp;
                  <span className="text-slate-300">{apiStats.hourly}</span>
                </span>
              </>
            )}
          </div>
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
