export const SEVERITY_CONFIG = {
  ok: {
    label: 'Healthy',
    ring: '#22c55e',
    bg: 'bg-green-500/10',
    text: 'text-green-400',
    border: 'border-green-500/30',
    dot: 'bg-green-400',
  },
  info: {
    label: 'Info',
    ring: '#60a5fa',
    bg: 'bg-blue-500/10',
    text: 'text-blue-400',
    border: 'border-blue-500/30',
    dot: 'bg-blue-400',
  },
  warning: {
    label: 'Warning',
    ring: '#f59e0b',
    bg: 'bg-amber-500/10',
    text: 'text-amber-400',
    border: 'border-amber-500/30',
    dot: 'bg-amber-400',
  },
  critical: {
    label: 'Critical',
    ring: '#ef4444',
    bg: 'bg-red-500/10',
    text: 'text-red-400',
    border: 'border-red-500/30',
    dot: 'bg-red-400',
  },
  unavailable: {
    label: 'Error',
    ring: '#6b7280',
    bg: 'bg-slate-500/10',
    text: 'text-slate-400',
    border: 'border-slate-500/30',
    dot: 'bg-slate-400',
  },
  coming_soon: {
    label: 'Coming Soon',
    ring: '#6b7280',
    bg: 'bg-slate-500/10',
    text: 'text-slate-500',
    border: 'border-slate-700',
    dot: 'bg-slate-600',
  },
}

export function getSeverityConfig(severity) {
  return SEVERITY_CONFIG[severity] || SEVERITY_CONFIG.unavailable
}
