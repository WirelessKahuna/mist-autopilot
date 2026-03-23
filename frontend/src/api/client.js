import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 60000,
  headers: { 'Content-Type': 'application/json' },
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

export const getOrgSummary  = ()         => api.get('/org/summary')
export const getSites        = ()         => api.get('/org/sites')
export const runModule       = (moduleId) => api.get(`/modules/${moduleId}`)
export const listModules     = ()         => api.get('/modules/')
export const getHealth       = ()         => api.get('/health')

export default api
export const getStats = () => api.get('/org/stats')
