import { useState, useEffect, useCallback } from 'react'

const STORAGE_KEY = 'pplx_admin_token'

export function useAuth() {
  const [adminToken, setAdminToken] = useState<string>(() => {
    return localStorage.getItem(STORAGE_KEY) || ''
  })
  const [isAuthenticated, setIsAuthenticated] = useState(false)

  useEffect(() => {
    setIsAuthenticated(!!adminToken)
  }, [adminToken])

  const login = useCallback((token: string) => {
    const trimmedToken = token.trim()
    if (trimmedToken) {
      setAdminToken(trimmedToken)
      localStorage.setItem(STORAGE_KEY, trimmedToken)
    }
  }, [])

  const logout = useCallback(() => {
    setAdminToken('')
    localStorage.removeItem(STORAGE_KEY)
  }, [])

  return {
    adminToken,
    isAuthenticated,
    login,
    logout,
  }
}
