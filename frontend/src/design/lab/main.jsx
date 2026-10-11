import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import DesignLab from './DesignLab'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <DesignLab />
  </StrictMode>,
)
