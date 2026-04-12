import axios from 'axios'

// Session token management
// Stored in sessionStorage (cleared on tab close)
const SESSION_KEY = 'mist_session_token'

export const getSessionToken = () => sessionStorage.getItem(SESSION_KEY)
export const setSessionToken = (token) => sessionStorage.setItem(SESSION_KEY, token)
export const clearSessionToken = () => sessionStorage.removeItem(SESSION_KEY)

const api = axios.create({
  baseURL: '/api',
  timeout: 120000,
  headers: { 'Content-Type': 'application/json' },
})

// Attach session token to every request if present
api.interceptors.request.use(config => {
  const token = getSessionToken()
  if (token) {
    config.headers['X-Session-Token'] = token
  }
  return config
})

api.interceptors.response.use(
  res => res.data,
  err => {
    const message =
      err.response?.data?.detail ||
      err.response?.data?.message ||
      err.message ||
      'Unknown error'
    return Promise.reject(new Error(message))
  }
)

// Org summary + stats
export const getOrgSummary  = ()         => api.get('/org/summary')
export const getSites        = ()         => api.get('/org/sites')
export const getStats        = ()         => api.get('/org/stats')
export const runModule       = (moduleId) => api.get(`/modules/${moduleId}`)
export const listModules     = ()         => api.get('/modules/')
export const getHealth       = ()         => api.get('/health')

// Credentials API
export const connectOrg = (apiToken) =>
  api.post('/credentials/connect', { api_token: apiToken })

export const selectSites = (siteIds) =>
  api.post('/credentials/sites', { site_ids: siteIds })

export const clearSession = () =>
  api.delete('/credentials/session')

export default api
