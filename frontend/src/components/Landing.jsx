import React from 'react'

/**
 * Landing.jsx
 * First-visit landing page shown when no saved orgs exist and no active session.
 *
 * Two-column layout on lg+: pitch on the left, dashboard screenshot on the right.
 * Stacks vertically on smaller screens.
 *
 * The "Connect an Org" CTA opens the OrgCredentials modal via onConnect.
 */
export default function Landing({ onConnect }) {
  return (
    <div className="min-h-screen bg-slate-950 flex flex-col">

      {/* Top nav / brand strip */}
      <header className="px-6 sm:px-10 py-5 flex items-center justify-between border-b border-slate-900">
        <div className="flex items-baseline gap-3">
          <h1 className="text-lg font-semibold text-white tracking-tight">Mist Autopilot</h1>
          <span className="text-xs text-slate-500 hidden sm:inline">Self-Driving Network Review</span>
        </div>
        <nav className="flex items-center gap-5 text-xs">
          <a
            href="https://github.com/WirelessKahuna/mist-autopilot"
            target="_blank"
            rel="noopener noreferrer"
            className="text-slate-400 hover:text-slate-200 transition-colors"
          >
            GitHub ↗
          </a>
        </nav>
      </header>

      {/* Main content */}
      <main className="flex-1 px-6 sm:px-10 py-8 lg:py-10">
        <div className="max-w-screen-xl mx-auto grid grid-cols-1 lg:grid-cols-5 gap-10 lg:gap-14 items-start">

          {/* ── Left: pitch + CTA ─────────────────────────────────────────── */}
          <div className="lg:col-span-2 space-y-7">

            <div className="space-y-4">
              <h2 className="text-3xl sm:text-4xl font-semibold text-white leading-tight tracking-tight">
                Review an entire Mist org in under a minute.
              </h2>
              <p className="text-sm sm:text-base text-slate-400 leading-relaxed">
                Mist Autopilot runs twelve analysis modules against your live Mist APIs in parallel
                and returns a scored, explained health report. Every finding includes a specific
                remediation; every critical finding links straight to the Mist page that resolves it.
              </p>
            </div>

            {/* CTA */}
            <div className="space-y-3">
              <button
                onClick={onConnect}
                className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg bg-mist-600 hover:bg-mist-500 text-white text-sm font-medium transition-colors shadow-lg shadow-mist-600/20"
              >
                Connect an Org
                <span className="text-mist-200">→</span>
              </button>
              <p className="text-xs text-slate-500">
                Paste a Mist Org API Token. Observer role is sufficient.
              </p>
            </div>

            {/* Trust callouts */}
            <div className="pt-2 space-y-2.5 text-xs">
              <div className="flex items-start gap-2.5">
                <span className="text-green-400 mt-0.5">●</span>
                <span className="text-slate-400">
                  <span className="text-slate-200 font-medium">Read-only by design.</span>
                  {' '}Autopilot never writes to your org.
                </span>
              </div>
              <div className="flex items-start gap-2.5">
                <span className="text-mist-400 mt-0.5">●</span>
                <span className="text-slate-400">
                  <span className="text-slate-200 font-medium">Any Mist cloud.</span>
                  {' '}All twelve geographic clouds auto-detected.
                </span>
              </div>
              <div className="flex items-start gap-2.5">
                <span className="text-amber-400 mt-0.5">●</span>
                <span className="text-slate-400">
                  <span className="text-slate-200 font-medium">Zero data persistence.</span>
                  {' '}No database, no logs, no telemetry.
                </span>
              </div>
              <div className="flex items-start gap-2.5">
                <span className="text-slate-400 mt-0.5">●</span>
                <span className="text-slate-400">
                  <span className="text-slate-200 font-medium">Any org, any size.</span>
                  {' '}From 3-site labs to 500-site retail fleets.
                </span>
              </div>
            </div>

            {/* Secondary links */}
            <div className="pt-3 border-t border-slate-900 flex flex-wrap items-center gap-x-5 gap-y-2 text-xs">
              <a
                href="https://github.com/WirelessKahuna/mist-autopilot/blob/main/CUSTOMER_IMPACT.md"
                target="_blank"
                rel="noopener noreferrer"
                className="text-slate-400 hover:text-slate-200 transition-colors"
              >
                Why customers deploy this ↗
              </a>
              <a
                href="https://github.com/WirelessKahuna/mist-autopilot#readme"
                target="_blank"
                rel="noopener noreferrer"
                className="text-slate-400 hover:text-slate-200 transition-colors"
              >
                Full documentation ↗
              </a>
            </div>
          </div>

          {/* Right: dashboard screenshot */}
          <div className="lg:col-span-3">
            <div className="relative rounded-xl overflow-hidden border border-slate-800 shadow-2xl shadow-black/50">
              <img
                src="/dashboard-preview.png"
                alt="Mist Autopilot dashboard showing 12 analysis module tiles with health scores, severity badges, and per-site summaries."
                className="w-full h-auto block max-h-[calc(100vh-11rem)] object-contain object-top"
                loading="eager"
              />
              {/* subtle gradient overlay at the bottom to fade any screenshot edge */}
              <div className="absolute inset-x-0 bottom-0 h-16 bg-gradient-to-t from-slate-950 to-transparent pointer-events-none" />
            </div>
            <p className="mt-3 text-xs text-slate-500 text-center lg:text-left">
              Live dashboard: twelve modules, scored and explained, with drill-downs and a PDF export.
            </p>
          </div>

        </div>
      </main>

      {/* Footer */}
      <footer className="px-6 sm:px-10 py-5 border-t border-slate-900">
        <div className="max-w-screen-xl mx-auto flex flex-wrap items-center justify-between gap-3 text-xs text-slate-500">
          <span>
            Built for the HPE / Juniper Mist Field PLM AI Ops Hackathon · April 2026
          </span>
          <span>
            Team Signal &amp; Noise
          </span>
        </div>
      </footer>

    </div>
  )
}
