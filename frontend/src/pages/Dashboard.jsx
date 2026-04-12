import React, { useEffect, useState, useCallback } from 'react'
import OrgHeader from '../components/OrgHeader'
import ModuleTile from '../components/ModuleTile'
import DrillDown from '../components/DrillDown'
import OrgCredentials from '../components/OrgCredentials'
import { getOrgSummary, getStats, clearSession, clearSessionToken, getSessionToken } from '../api/client'

function ErrorBanner({ message, onRetry }) {
  return (
    <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-4 flex items-start justify-between gap-4">
      <div>
        <p className="text-sm font-medium text-red-400">Failed to load org data</p>
        <p className="text-xs text-red-400/70 mt-1">{message}</p>
      </div>
      <button
        onClick={onRetry}
        className="text-xs text-red-400 hover:text-red-200 border border-red-500/30 rounded px-3 py-1.5 shrink-0 transition-colors"
      >
        Retry
      </button>
    </div>
  )
}

function LoadingGrid() {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
      {Array.from({ length: 12 }).map((_, i) => (
        <div key={i} className="rounded-xl border border-slate-800 bg-slate-900 p-5 h-44 animate-pulse">
          <div className="flex items-center gap-3 mb-4">
            <div className="w-8 h-8 rounded-lg bg-slate-800" />
            <div className="flex-1 space-y-2">
              <div className="h-3 bg-slate-800 rounded w-3/4" />
              <div className="h-2 bg-slate-800 rounded w-1/2" />
            </div>
          </div>
          <div className="space-y-2">
            <div className="h-2 bg-slate-800 rounded" />
            <div className="h-2 bg-slate-800 rounded w-5/6" />
          </div>
        </div>
      ))}
    </div>
  )
}

function formatTime(date) {
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

export default function Dashboard() {
  const [org, setOrg]                     = useState(null)
  const [loading, setLoading]             = useState(true)
  const [error, setError]                 = useState(null)
  const [lastUpdated, setLastUpdated]     = useState(null)
  const [drillDownModule, setDrillDownModule] = useState(null)
  const [apiStats, setApiStats]           = useState(null)
  const [showCredentials, setShowCredentials] = useState(false)

  const [scanningOrg, setScanningOrg]       = useState(null)  // name of org being scanned

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await getOrgSummary()
      setOrg(data)
      setLastUpdated(formatTime(new Date()))
      setScanningOrg(null)
      try {
        const stats = await getStats()
        setApiStats(stats)
      } catch (_) {}
    } catch (e) {
      setError(e.message)
      setScanningOrg(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const handleConnected = useCallback((info) => {
    // Immediately clear old org data and show loading skeleton
    setOrg(null)
    setError(null)
    setLastUpdated(null)
    setApiStats(null)
    setScanningOrg(info.orgName)
    load()
  }, [load])

  const handleDisconnect = useCallback(async () => {
    await clearSession()
    clearSessionToken()
    setOrg(null)
    setScanningOrg(null)
    load()
  }, [load])

  return (
    <div className="min-h-screen bg-slate-950 px-4 py-6 sm:px-8">
      <div className="max-w-screen-xl mx-auto">

        <OrgHeader
          org={org}
          onRefresh={load}
          loading={loading}
          lastUpdated={lastUpdated}
          apiStats={apiStats}
          onOpenCredentials={() => setShowCredentials(true)}
        />

        {/* Scanning new org banner */}
        {scanningOrg && loading && (
          <div className="mb-4 flex items-center gap-3 bg-mist-600/10 border border-mist-600/30 rounded-lg px-4 py-2.5">
            <span className="animate-spin text-mist-400">↻</span>
            <span className="text-xs text-mist-400">
              Scanning <span className="font-medium text-mist-300">{scanningOrg}</span>…
            </span>
          </div>
        )}

        {/* Active session banner (shown after scan completes) */}
        {getSessionToken() && org && !scanningOrg && (
          <div className="mb-4 flex items-center justify-between bg-slate-800/50 border border-slate-700 rounded-lg px-4 py-2">
            <span className="text-xs text-slate-400">
              Viewing <span className="font-medium text-slate-200">{org.org_name}</span>
              <span className="text-slate-600 mx-2">·</span>
              <span className="text-slate-500">{org.site_count} site{org.site_count !== 1 ? 's' : ''} scanned</span>
            </span>
            <button
              onClick={handleDisconnect}
              className="text-xs text-slate-500 hover:text-red-400 transition-colors"
            >
              Disconnect
            </button>
          </div>
        )}

        {error && <div className="mb-6"><ErrorBanner message={error} onRetry={load} /></div>}

        {loading && !org
          ? <LoadingGrid />
          : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
              {org?.modules?.map(module => (
                <ModuleTile
                  key={module.module_id}
                  module={module}
                  onDrillDown={setDrillDownModule}
                />
              ))}
            </div>
          )
        }

        {/* Summary bar */}
        {org && !loading && (
          <div className="mt-8 flex flex-wrap gap-6 text-xs text-slate-500 border-t border-slate-800 pt-5">
            {['ok', 'warning', 'critical'].map(sev => {
              const count = org.modules?.filter(m => m.severity === sev).length ?? 0
              const labels = { ok: '✓ Healthy', warning: '⚠ Warning', critical: '✕ Critical' }
              const colors = { ok: 'text-green-400', warning: 'text-amber-400', critical: 'text-red-400' }
              return (
                <span key={sev} className={count > 0 ? colors[sev] : 'text-slate-600'}>
                  {labels[sev]}: {count}
                </span>
              )
            })}
            <span className="ml-auto">
              {org.modules?.filter(m => m.status === 'coming_soon').length} modules in development
            </span>
          </div>
        )}
      </div>

      {drillDownModule && (
        <DrillDown
          module={drillDownModule}
          onClose={() => setDrillDownModule(null)}
        />
      )}

      {showCredentials && (
        <OrgCredentials
          onConnected={handleConnected}
          onClose={() => setShowCredentials(false)}
        />
      )}
    </div>
  )
}
