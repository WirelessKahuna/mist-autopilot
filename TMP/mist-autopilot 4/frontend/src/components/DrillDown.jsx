import React from 'react'
import { getSeverityConfig } from '../utils/severity'

// Score legend — shown in every drill-down
const SCORE_LEGEND = [
  { range: '80 – 100', label: 'Healthy',  color: 'text-green-400',  dot: 'bg-green-400' },
  { range: '60 – 79',  label: 'Info',     color: 'text-blue-400',   dot: 'bg-blue-400'  },
  { range: '40 – 59',  label: 'Warning',  color: 'text-amber-400',  dot: 'bg-amber-400' },
  { range: '0 – 39',   label: 'Critical', color: 'text-red-400',    dot: 'bg-red-400'   },
]

// Module-specific context notes shown beneath the legend
const MODULE_CONTEXT = {
  sle_sentinel: (
    'The health score reflects anomaly detection — it measures how many SLE metrics ' +
    'have dropped below configured thresholds or fallen from their 7-day baseline. ' +
    'A score of 100 means all monitored SLEs are within normal operating range, ' +
    'not that every SLE reads 100%. Actual SLE percentages are shown per-site below.'
  ),
  config_drift: (
    'The score reflects the number and severity of SSID configuration inconsistencies ' +
    'and VLAN collisions detected. A score of 100 means no drift or security boundary ' +
    'issues were found across all sites.'
  ),
  ap_lifecycle: (
    'The score reflects firmware compliance, connectivity, and hardware lifecycle status. ' +
    'A score of 100 means all APs are on current firmware, connected, and on supported hardware.'
  ),
  client_experience: (
    'Trends are measured by comparing the last 7 days of SLE scores against the prior ' +
    '23-day baseline. A 10% relative change in either direction is considered notable. ' +
    'For sites where weekends account for less than 20% of traffic, weekend samples are ' +
    'excluded to avoid low-utilization noise skewing the trend. A score of 100 means ' +
    'all sites are stable or improving — no metrics degraded ≥10%.'
  ),
  secure_scope: (
    'The score reflects wireless security posture across all SSIDs and sites. ' +
    'Critical findings indicate immediate security boundary failures (open SSIDs with ' +
    'no VLAN, or shared VLANs between open and protected SSIDs). Warnings are important ' +
    'gaps (PMF disabled, rogue detection off, PSK reuse). Info findings are educational — ' +
    'transition modes like OWE and WPA3/WPA2 mixed mode are expected during migration ' +
    'but should be planned for eventual removal.'
  ),
  roam_guard: (
    'Roaming health is scored using the 7-day SLE roaming metric combined with fast roam ' +
    'event data. Sticky client findings require both SLE signal-quality degradation AND ' +
    'corroborating fast roam events — a single signal alone is flagged as informational only. ' +
    '802.11r warnings fire only on 802.1X SSIDs where full RADIUS re-auth on every roam is ' +
    'the real cost. High Density data rate recommendations only appear when roaming SLE is ' +
    'below 80 — they are a remediation suggestion, not a standalone best-practice audit.'
  ),
}

function ScoreLegend({ moduleId }) {
  const contextNote = MODULE_CONTEXT[moduleId]
  return (
    <section>
      <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-3">
        Score legend
      </h3>
      <div className="rounded-xl border border-slate-800 bg-slate-900 px-4 py-3 space-y-2">
        {SCORE_LEGEND.map(({ range, label, color, dot }) => (
          <div key={range} className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className={`w-2 h-2 rounded-full shrink-0 ${dot}`} />
              <span className={`text-xs font-medium ${color}`}>{label}</span>
            </div>
            <span className="text-xs text-slate-500 font-mono">{range}</span>
          </div>
        ))}
        {contextNote && (
          <p className="text-xs text-slate-500 border-t border-slate-800 pt-2 mt-1 leading-relaxed">
            {contextNote}
          </p>
        )}
      </div>
    </section>
  )
}

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

          {/* Score legend — always shown */}
          <ScoreLegend moduleId={module.module_id} />

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
