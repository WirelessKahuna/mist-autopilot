import React, { useState } from 'react'

export default function SitePicker({ orgName, activeSites, inactiveCount, onConfirm, onBack }) {
  const [selected, setSelected] = useState(new Set(activeSites.map(s => s.id)))

  const toggleSite = (id) => {
    setSelected(prev => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  const toggleAll = () => {
    if (selected.size === activeSites.length) {
      setSelected(new Set())
    } else {
      setSelected(new Set(activeSites.map(s => s.id)))
    }
  }

  const allSelected = selected.size === activeSites.length
  const noneSelected = selected.size === 0

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="bg-slate-900 border border-slate-700 rounded-2xl w-full max-w-lg mx-4 shadow-2xl">

        {/* Header */}
        <div className="px-6 pt-6 pb-4 border-b border-slate-800">
          <h2 className="text-base font-semibold text-white">Select Sites to Scan</h2>
          <p className="text-xs text-slate-400 mt-1">{orgName}</p>
        </div>

        {/* Select all toggle */}
        <div className="px-6 py-3 border-b border-slate-800 flex items-center justify-between">
          <button
            onClick={toggleAll}
            className="text-xs text-mist-400 hover:text-mist-300 transition-colors"
          >
            {allSelected ? 'Deselect all' : 'Select all'}
          </button>
          <span className="text-xs text-slate-500">
            {selected.size} of {activeSites.length} selected
          </span>
        </div>

        {/* Site list */}
        <div className="overflow-y-auto max-h-72 px-6 py-3 space-y-1">
          {activeSites.map(site => (
            <label
              key={site.id}
              className="flex items-center gap-3 py-2 px-3 rounded-lg hover:bg-slate-800 cursor-pointer transition-colors"
            >
              <input
                type="checkbox"
                checked={selected.has(site.id)}
                onChange={() => toggleSite(site.id)}
                className="w-4 h-4 rounded accent-mist-500"
              />
              <div className="flex-1 min-w-0">
                <span className="text-sm text-slate-200 truncate block">{site.name}</span>
              </div>
              <span className="text-xs text-slate-500 shrink-0">
                {site.ap_count} AP{site.ap_count !== 1 ? 's' : ''}
              </span>
            </label>
          ))}

          {/* Inactive sites rollup */}
          {inactiveCount > 0 && (
            <div className="flex items-center gap-3 py-2 px-3 rounded-lg opacity-40">
              <div className="w-4 h-4 rounded border border-slate-600" />
              <span className="text-sm text-slate-500 italic">
                {inactiveCount} inactive site{inactiveCount !== 1 ? 's' : ''} (no APs assigned)
              </span>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-slate-800 flex items-center justify-between gap-3">
          <button
            onClick={onBack}
            className="text-sm text-slate-400 hover:text-slate-200 transition-colors"
          >
            ← Back
          </button>
          <button
            onClick={() => onConfirm(Array.from(selected))}
            disabled={noneSelected}
            className="px-5 py-2 rounded-lg bg-mist-600 hover:bg-mist-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-medium transition-colors"
          >
            Scan {selected.size} Site{selected.size !== 1 ? 's' : ''}
          </button>
        </div>
      </div>
    </div>
  )
}
