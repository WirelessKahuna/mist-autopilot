/**
 * Saved Orgs — localStorage persistence for remembered orgs
 *
 * Each saved org:
 *   { id, name, token, savedAt }
 *
 * The token is stored in localStorage only when the user explicitly
 * checks "Remember this org". Users can delete saved orgs at any time.
 */

const STORAGE_KEY    = 'mist_saved_orgs'
const LAST_USED_KEY  = 'mist_last_used_org_id'

export function getSavedOrgs() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]')
  } catch {
    return []
  }
}

export function saveOrg(orgId, orgName, token) {
  const orgs = getSavedOrgs().filter(o => o.id !== orgId)
  orgs.unshift({ id: orgId, name: orgName, token, savedAt: Date.now() })
  localStorage.setItem(STORAGE_KEY, JSON.stringify(orgs))
}

export function forgetOrg(orgId) {
  const orgs = getSavedOrgs().filter(o => o.id !== orgId)
  localStorage.setItem(STORAGE_KEY, JSON.stringify(orgs))
  if (localStorage.getItem(LAST_USED_KEY) === orgId) {
    localStorage.removeItem(LAST_USED_KEY)
  }
}

export function isOrgSaved(orgId) {
  return getSavedOrgs().some(o => o.id === orgId)
}

export function setLastUsedOrg(orgId) {
  localStorage.setItem(LAST_USED_KEY, orgId)
}

export function getLastUsedOrg() {
  const lastId = localStorage.getItem(LAST_USED_KEY)
  if (!lastId) return null
  return getSavedOrgs().find(o => o.id === lastId) || null
}

export function clearLastUsedOrg() {
  localStorage.removeItem(LAST_USED_KEY)
}
