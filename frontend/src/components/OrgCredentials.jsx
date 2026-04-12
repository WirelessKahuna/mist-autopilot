import React, { useState, useEffect } from 'react'
import { connectOrg, selectSites, setSessionToken, clearSessionToken } from '../api/client'
import { getSavedOrgs, saveOrg, forgetOrg, isOrgSaved, setLastUsedOrg } from '../utils/savedOrgs'
import SitePicker from './SitePicker'

const STEPS = { INPUT: 'input', SITE_PICKER: 'site_picker' }

export default function OrgCredentials({ onConnected, onClose }) {
  const [step, setStep]           = useState(STEPS.INPUT)
  const [token, setToken]         = useState('')
  const [connecting, setConnecting] = useState(false)
  const [error, setError]         = useState(null)
  const [remember, setRemember]   = useState(false)
  const [savedOrgs, setSavedOrgs] = useState(getSavedOrgs())
  const [connectResult, setConnectResult] = useState(null)

  useEffect(() => { setSavedOrgs(getSavedOrgs()) }, [])

  const handleConnect = async () => {
    if (!token.trim()) return
    setConnecting(true)
    setError(null)
    try {
      const result = await connectOrg(token.trim())
      setSessionToken(result.session_id)
      setConnectResult(result)
      setStep(STEPS.SITE_PICKER)
    } catch (e) {
      setError(e.message)
    } finally {
      setConnecting(false)
    }
  }

  const handleSiteConfirm = async (siteIds) => {
    try {
      await selectSites(siteIds)
      if (remember && connectResult) {
        saveOrg(connectResult.org_id, connectResult.org_name, token.trim())
        setSavedOrgs(getSavedOrgs())
      }
      setLastUsedOrg(connectResult.org_id)
      onConnected({
        orgName: connectResult.org_name,
        orgId:   connectResult.org_id,
        siteCount: siteIds.length,
      })
      onClose()
    } catch (e) {
      setError(e.message)
      setStep(STEPS.INPUT)
    }
  }

  const handleLoadSaved = (saved) => {
    setToken(saved.token)
    setError(null)
  }

  const handleForget = (orgId, e) => {
    e.stopPropagation()
    forgetOrg(orgId)
    setSavedOrgs(getSavedOrgs())
  }

  if (step === STEPS.SITE_PICKER && connectResult) {
    return (
      <SitePicker
        orgName={connectResult.org_name}
        activeSites={connectResult.active_sites}
        inactiveCount={connectResult.inactive_count}
        onConfirm={handleSiteConfirm}
        onBack={() => setStep(STEPS.INPUT)}
      />
    )
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="bg-slate-900 border border-slate-700 rounded-2xl w-full max-w-md mx-4 shadow-2xl">

        {/* Header */}
        <div className="px-6 pt-6 pb-4 border-b border-slate-800 flex items-start justify-between">
          <div>
            <h2 className="text-base font-semibold text-white">Connect an Org</h2>
            <p className="text-xs text-slate-400 mt-1">Enter a Mist Org API Token to begin</p>
          </div>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-300 text-lg leading-none mt-0.5">✕</button>
        </div>

        <div className="px-6 py-5 space-y-5">

          {/* Token input */}
          <div>
            <label className="block text-xs font-medium text-slate-400 mb-1.5">
              Org API Token
            </label>
            <input
              type="password"
              value={token}
              onChange={e => setToken(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleConnect()}
              placeholder="Paste your Org API Token here"
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2.5 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-mist-500 transition-colors"
            />
          </div>

          {/* Help text */}
          <div className="bg-slate-800/50 rounded-lg p-3 text-xs text-slate-400 space-y-1.5">
            <p className="font-medium text-slate-300">How to generate an Org Token:</p>
            <p>1. Log in to <span className="text-mist-400">manage.mist.com</span></p>
            <p>2. Go to <span className="text-slate-300">Organization → Settings → API Token</span></p>
            <p>3. Create a token with <span className="text-slate-300">Observer</span> role</p>
            <p className="text-slate-500 pt-1">Observer (read-only) is sufficient — Mist Autopilot never writes to your org.</p>
          </div>

          {/* Remember checkbox */}
          <label className="flex items-center gap-2.5 cursor-pointer">
            <input
              type="checkbox"
              checked={remember}
              onChange={e => setRemember(e.target.checked)}
              className="w-4 h-4 rounded accent-mist-500"
            />
            <span className="text-xs text-slate-400">Remember this org across browser sessions</span>
          </label>

          {/* Error */}
          {error && (
            <div className="bg-red-500/10 border border-red-500/30 rounded-lg px-3 py-2 text-xs text-red-400">
              {error}
            </div>
          )}

          {/* Connect button */}
          <button
            onClick={handleConnect}
            disabled={connecting || !token.trim()}
            className="w-full py-2.5 rounded-lg bg-mist-600 hover:bg-mist-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-medium transition-colors"
          >
            {connecting ? 'Connecting…' : 'Connect →'}
          </button>
        </div>

        {/* Saved orgs */}
        {savedOrgs.length > 0 && (
          <div className="px-6 pb-5">
            <p className="text-xs font-medium text-slate-500 mb-2">Saved orgs</p>
            <div className="space-y-1">
              {savedOrgs.map(org => (
                <div
                  key={org.id}
                  onClick={() => handleLoadSaved(org)}
                  className="flex items-center justify-between px-3 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 cursor-pointer transition-colors group"
                >
                  <div>
                    <p className="text-sm text-slate-200">{org.name}</p>
                    <p className="text-xs text-slate-500">{org.id.slice(0, 8)}…</p>
                  </div>
                  <button
                    onClick={(e) => handleForget(org.id, e)}
                    className="text-xs text-slate-600 hover:text-red-400 transition-colors opacity-0 group-hover:opacity-100"
                  >
                    Forget
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
