import React from 'react'
import { getSeverityConfig } from '../utils/severity'

export default function ScoreRing({ score, severity, size = 80 }) {
  const cfg = getSeverityConfig(severity)
  const radius = 28
  const circumference = 2 * Math.PI * radius
  const pct = score !== null && score !== undefined ? score / 100 : 0
  const offset = circumference * (1 - pct)
  const isPlaceholder = score === null || score === undefined

  return (
    <div className="relative flex items-center justify-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox="0 0 64 64">
        {/* Track */}
        <circle
          cx="32" cy="32" r={radius}
          fill="none"
          stroke="rgba(255,255,255,0.06)"
          strokeWidth="5"
        />
        {/* Fill */}
        {!isPlaceholder && (
          <circle
            cx="32" cy="32" r={radius}
            fill="none"
            stroke={cfg.ring}
            strokeWidth="5"
            strokeDasharray={circumference}
            strokeDashoffset={offset}
            strokeLinecap="round"
            style={{
              transform: 'rotate(-90deg)',
              transformOrigin: '50% 50%',
              transition: 'stroke-dashoffset 0.8s ease',
            }}
          />
        )}
      </svg>
      <div className="absolute inset-0 flex items-center justify-center">
        {isPlaceholder ? (
          <span className="text-slate-600 text-lg">—</span>
        ) : (
          <span className={`font-semibold text-sm ${cfg.text}`}>{score}</span>
        )}
      </div>
    </div>
  )
}
