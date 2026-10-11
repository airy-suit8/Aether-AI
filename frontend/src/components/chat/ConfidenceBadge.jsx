import React from 'react'
import './ConfidenceBadge.css'

export default function ConfidenceBadge({ score }) {
  let type = 'high'
  let label = 'High Confidence'
  
  if (score < 0.3) {
    type = 'low'
    label = 'Low Confidence'
  } else if (score < 0.6) {
    type = 'medium'
    label = 'Moderate Confidence'
  }

  return (
    <div className={`confidence-badge confidence-${type}`}>
      <span className="confidence-dot" />
      <span>{label} ({(score * 100).toFixed(1)}%)</span>
    </div>
  )
}
