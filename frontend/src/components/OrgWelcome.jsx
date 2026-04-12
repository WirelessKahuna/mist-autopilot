import React from 'react'
import { forgetOrg } from '../utils/savedOrgs'

/**
 * OrgWelcome — shown on page load when multiple saved orgs exist.
 * Lists orgs as one-click connect buttons.
 * Single saved org bypasses this screen (auto-connects in Dashboard).
 */
export default function OrgWelcome({ savedOrgs, onSelect, onConnectNew, onRefreshList }) {
  const handleForget = (orgId, e) => {
    e.stopPropagation()
    forgetOrg(orgId)
    onRefreshList()
  }

  return (
    <div className="min-h-screen bg-slate-950 flex items-center justify-center px-4">
      <div className="w-full max-w-sm">

        {/* Branding */}
        <div className="text-center mb-8">
          <h1 className="text-2xl font-semibold text-white tracking-tight">Mist Autopilot</h1>
          <p className="text-sm text-slate-500 mt-1">Self-Driving Network Review</p>
        </div>

        {/* Org list */}
        <div className="bg-slate-900 border border-slate-700 rounded-2xl overflow-hidden shadow-2xl">
          <div className="px-5 py-4 border-b border-slate-800">
            <p className="text-xs font-medium text-slate-400">Select an org to scan</p>
          </div>

          <div className="divide-y divide-slate-800">
            {savedOrgs.map(org => (
              <div
                key={org.id}
                onClick={() => onSelect(org)}
                className="flex items-center justify-between px-5 py-4 hover:bg-slate-800 cursor-pointer transition-colors group"
              >
                <div>
                  <p className="text-sm font-medium text-slate-100">{org.name}</p>
                  <p className="text-xs text-slate-500 mt-0.5">{org.id.slice(0, 8)}…</p>
                </div>
                <div className="flex items-center gap-3">
                  <button
                    onClick={(e) => handleForget(org.id, e)}
                    className="text-xs text-slate-600 hover:text-red-400 transition-colors opacity-0 group-hover:opacity-100"
                  >
                    Forget
                  </button>
                  <span className="text-slate-600 text-sm">→</span>
                </div>
              </div>
            ))}
          </div>

          <div className="px-5 py-4 border-t border-slate-800">
            <button
              onClick={onConnectNew}
              className="w-full text-sm text-slate-400 hover:text-slate-200 transition-colors text-left"
            >
              + Connect a new org
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
