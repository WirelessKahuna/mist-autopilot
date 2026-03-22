import React from 'react'
import { getSeverityConfig } from '../utils/severity'

function FindingCard({ finding }) {
  const cfg = getSeverityConfig(finding.severity)
  return (
    <div className={`rounded-lg border p-4 ${cfg.border} bg-slate-900`}>
      <div className="flex items-start justify-between gap-3 mb-2">
        <span className="text-sm font-medium text-slate-100">{finding.title}</span>
        <span className={`text-xs px-2 py-0.5 rounded-full shrink-0 ${cfg.bg} ${cfg.text}`}>
          {finding.severity}
        </span>
      </div>
      <p className="text-xs text-slate-400 mb-2 leading-relaxed">{finding.detail}</p>
      {finding.affected?.length > 0 && (
        <div className="flex flex-wrap gap-1 mb-2">
          {finding.affected.map((a, i) => (
            <span key={i} className="text-xs bg-slate-800 text-slate-300 px-2 py-0.5 rounded font-mono">
              {a}
            </span>
          ))}
        </div>
      )}
      {finding.recommendation && (
        <p className="text-xs text-mist-400 border-t border-slate-800 pt-2 mt-2">
          ↳ {finding.recommendation}
        </p>
      )}
    </div>
  )
}

function SiteRow({ site }) {
  const cfg = getSeverityConfig(site.severity)
  return (
    <div className="flex items-center justify-between py-2 border-b border-slate-800 last:border-0">
      <div className="flex items-center gap-3">
        <span className={`w-2 h-2 rounded-full shrink-0 ${cfg.dot}`} />
        <span className="text-sm text-slate-200">{site.site_name}</span>
        <span className="text-xs text-slate-500">{site.findings?.length ?? 0} findings</span>
      </div>
      <span className={`text-sm font-semibold ${cfg.text}`}>
        {site.score !== null && site.score !== undefined ? site.score : '—'}
      </span>
    </div>
  )
}

export default function DrillDown({ module, onClose }) {
  if (!module) return null

  const orgFindings = module.findings ?? []
  const sites = module.sites ?? []

  return (
    <div className="fixed inset-0 z-50 flex justify-end" onClick={onClose}>
      <div
        className="relative w-full max-w-xl h-full bg-slate-950 border-l border-slate-800 overflow-y-auto shadow-2xl"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="sticky top-0 bg-slate-950 border-b border-slate-800 px-6 py-4 flex items-center justify-between z-10">
          <div className="flex items-center gap-3">
            <span className="text-xl">{module.icon}</span>
            <div>
              <p className="font-medium text-slate-100">{module.display_name}</p>
              <p className="text-xs text-slate-500">{module.summary}</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-slate-500 hover:text-slate-200 text-xl transition-colors leading-none"
          >
            ✕
          </button>
        </div>

        <div className="px-6 py-5 space-y-7">

          {/* Org-level findings */}
          {orgFindings.length > 0 && (
            <section>
              <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-3">
                Findings ({orgFindings.length})
              </h3>
              <div className="space-y-3">
                {orgFindings.map((f, i) => <FindingCard key={i} finding={f} />)}
              </div>
            </section>
          )}

          {/* Per-site breakdown */}
          {sites.length > 0 && (
            <section>
              <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-3">
                Site Breakdown ({sites.length})
              </h3>
              <div className="rounded-xl border border-slate-800 bg-slate-900 px-4">
                {sites
                  .slice()
                  .sort((a, b) => (a.score ?? 101) - (b.score ?? 101))
                  .map(site => <SiteRow key={site.site_id} site={site} />)
                }
              </div>
            </section>
          )}

          {orgFindings.length === 0 && sites.length === 0 && (
            <p className="text-sm text-slate-500 text-center py-8">No findings to display.</p>
          )}
        </div>
      </div>
    </div>
  )
}
