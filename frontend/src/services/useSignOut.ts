import { startTransition, useCallback } from 'react'
import { useNavigate } from 'react-router'
import { useAuth } from './AuthContext'

/**
 * Sign out and show the start page. Both happen in one transition, so no workspace page is drawn
 * signed out in between (it would send the user to /login).
 */
export function useSignOut(): () => void {
  const { logout } = useAuth()
  const navigate = useNavigate()
  return useCallback(() => {
    startTransition(() => {
      navigate('/', { replace: true })
      logout()
    })
  }, [logout, navigate])
}
