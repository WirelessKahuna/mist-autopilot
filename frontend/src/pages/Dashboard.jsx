import React, { useEffect, useState, useCallback } from 'react'
import OrgHeader from '../components/OrgHeader'
import ModuleTile from '../components/ModuleTile'
import DrillDown from '../components/DrillDown'
import OrgCredentials from '../components/OrgCredentials'
import OrgWelcome from '../components/OrgWelcome'
import Landing from '../components/Landing'
import { getOrgSummary, getStats, clearSession, clearSessionToken, getSessionToken, setSessionToken, connectOrg, selectSites } from '../api/client'
import ReportGenerator from '../components/ReportGenerator'
import { getSavedOrgs, getLastUsedOrg, setLastUsedOrg } from '../utils/savedOrgs'

// Startup modes
const MODE = {
  BOOTING:     'booting',       // checking localStorage, haven't decided yet
  LANDING:     'landing',       // first visit: no saved orgs, no active session
  WELCOME:     'welcome',       // multiple saved orgs, show picker
  DASHBOARD:   'dashboard',     // normal dashboard view (also used while loading)
  CREDENTIALS: 'credentials',   // credentials modal open
}

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
  const [mode, setMode]           = useState(MODE.BOOTING)
  const [savedOrgs, setSavedOrgs] = useState([])
  const [org, setOrg]             = useState(null)
  const [loading, setLoading]     = useState(false)
  const [error, setError]         = useState(null)
  const [lastUpdated, setLastUpdated] = useState(null)
  const [drillDownModule, setDrillDownModule] = useState(null)
  const [apiStats, setApiStats]   = useState(null)
  const [scanningOrg, setScanningOrg] = useState(null)

  // Load dashboard data
  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    setMode(MODE.DASHBOARD)
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

  // Auto-connect a saved org (skip site picker, use all sites).
  // Flips to DASHBOARD mode immediately so the skeleton grid + scanning banner
  // render while the cloud-probe and site-selection happen, then load() takes
  // over for the actual data fetch.
  const autoConnect = useCallback(async (savedOrg) => {
    setOrg(null)
    setScanningOrg(savedOrg.name)
    setLoading(true)
    setMode(MODE.DASHBOARD)
    try {
      const result = await connectOrg(savedOrg.token)
      setSessionToken(result.session_id)
      await selectSites(result.active_sites.map(s => s.id))
      setLastUsedOrg(result.org_id)
      await load()
    } catch (e) {
      // Auto-connect failed: fall back to the landing page rather than silently
      // loading from env-var credentials. The user can reconnect from there.
      setScanningOrg(null)
      setLoading(false)
      setMode(MODE.LANDING)
    }
  }, [load])

  // Startup logic
  useEffect(() => {
    const orgs = getSavedOrgs()
    setSavedOrgs(orgs)

    if (orgs.length === 0) {
      setMode(MODE.LANDING)
      return
    }

    if (orgs.length === 1) {
      autoConnect(orgs[0])
      return
    }

    const lastUsed = getLastUsedOrg()
    if (lastUsed) {
      autoConnect(lastUsed)
    } else {
      setMode(MODE.WELCOME)
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // Handlers
  const handleConnected = useCallback((info) => {
    setOrg(null)
    setError(null)
    setLastUpdated(null)
    setApiStats(null)
    setScanningOrg(info.orgName)
    // Keep savedOrgs in sync in case Remember was checked in the modal.
    setSavedOrgs(getSavedOrgs())
    // Go straight to DASHBOARD mode. load() shows the skeleton grid with the
    // scanning banner while the actual scan runs, which is the same UX as the
    // saved-org reload path.
    load()
  }, [load])

  const handleDisconnect = useCallback(async () => {
    await clearSession()
    clearSessionToken()
    setOrg(null)
    setScanningOrg(null)
    const orgs = getSavedOrgs()
    setSavedOrgs(orgs)
    if (orgs.length === 0) {
      setMode(MODE.LANDING)
    } else if (orgs.length === 1) {
      autoConnect(orgs[0])
    } else {
      setMode(MODE.WELCOME)
    }
  }, [autoConnect])

  const handleWelcomeSelect = useCallback((savedOrg) => {
    autoConnect(savedOrg)
  }, [autoConnect])

  const handleWelcomeConnectNew = useCallback(() => {
    setMode(MODE.CREDENTIALS)
  }, [])

  const handleRefreshWelcomeList = useCallback(() => {
    const orgs = getSavedOrgs()
    setSavedOrgs(orgs)
    if (orgs.length === 0) {
      setMode(MODE.LANDING)
    }
  }, [])

  // Render

  // Booting, brief flash, shouldn't be seen
  if (mode === MODE.BOOTING) return null

  // Landing page: first visit with no saved orgs and no active session.
  // Also handles the credentials-modal-over-landing case.
  if (mode === MODE.LANDING || (mode === MODE.CREDENTIALS && !org && savedOrgs.length === 0)) {
    return (
      <>
        <Landing onConnect={() => setMode(MODE.CREDENTIALS)} />
        {mode === MODE.CREDENTIALS && (
          <OrgCredentials
            onConnected={handleConnected}
            onClose={() => setMode(MODE.LANDING)}
          />
        )}
      </>
    )
  }

  // Welcome screen (multiple saved orgs, no last used)
  if (mode === MODE.WELCOME) {
    return (
      <>
        <OrgWelcome
          savedOrgs={savedOrgs}
          onSelect={handleWelcomeSelect}
          onConnectNew={handleWelcomeConnectNew}
          onRefreshList={handleRefreshWelcomeList}
        />
        {mode === MODE.CREDENTIALS && (
          <OrgCredentials
            onConnected={handleConnected}
            onClose={() => setMode(MODE.WELCOME)}
          />
        )}
      </>
    )
  }

  // Credentials modal open over dashboard
  const showCredentials = mode === MODE.CREDENTIALS

  return (
    <div className="min-h-screen bg-slate-950 px-4 py-6 sm:px-8">
      <div className="max-w-screen-xl mx-auto">

        <OrgHeader
          org={org}
          onRefresh={load}
          loading={loading}
          lastUpdated={lastUpdated}
          apiStats={apiStats}
          onOpenCredentials={() => setMode(MODE.CREDENTIALS)}
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

        {/* Active session banner */}
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

        {org && !loading && (
          <div className="mt-8 border-t border-slate-800 pt-5 space-y-3">
            <div className="flex flex-wrap gap-6 text-xs text-slate-500">
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
            <ReportGenerator
              orgName={org.org_name}
              orgId={org.org_id}
              moduleResults={(org.modules || []).map(m => ({
                moduleId:   m.module_id,
                moduleName: m.display_name,
                moduleIcon: m.icon,
                status:     m.severity === 'ok' ? 'pass' : m.severity,
                findings:   (m.findings || []).map(f => ({
                  severity: f.severity,
                  site_id:  f.site_id || null,
                  message:  f.detail ? `${f.title}: ${f.detail}` : f.title,
                }))
              }))}
              siteNames={org.site_names || {}}
            />
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
          onClose={() => setMode(MODE.DASHBOARD)}
        />
      )}
    </div>
  )
}
