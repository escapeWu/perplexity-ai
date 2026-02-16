import { useState, useEffect, useCallback } from 'react'
import { fetchPoolStatus, fetchHeartbeatConfig, fetchFallbackConfig, fetchIncognitoConfig, PoolStatus, HeartbeatConfig, FallbackConfig, IncognitoConfig } from 'lib/api'
import { useAuth } from './useAuth'

export function usePool() {
  const { adminToken } = useAuth()
  const [data, setData] = useState<PoolStatus>({
    total: 0,
    available: 0,
    mode: '-',
    clients: [],
  })
  const [hbConfig, setHbConfig] = useState<HeartbeatConfig | null>(null)
  const [fallbackConfig, setFallbackConfig] = useState<FallbackConfig>({ fallback_to_auto: true })
  const [incognitoConfig, setIncognitoConfig] = useState<IncognitoConfig>({ enabled: false })
  const [isLoading, setIsLoading] = useState(false)
  const [lastSync, setLastSync] = useState<string | null>(null)

  const refreshData = useCallback(async () => {
    // Requires admin token for heartbeat config
    if (!adminToken) {
      // Just fetch pool status if no token
      try {
        const poolData = await fetchPoolStatus()
        setData(poolData)
        setLastSync(new Date().toLocaleTimeString('en-US', { hour12: false }))
      } catch (e) {
        console.error('Failed to fetch pool status:', e)
      }
      return
    }

    setIsLoading(true)
    try {
      const [poolData, hbResp, fallbackResp, incognitoResp] = await Promise.all([
        fetchPoolStatus(),
        fetchHeartbeatConfig(adminToken),
        fetchFallbackConfig(),
        fetchIncognitoConfig(),
      ])
      setData(poolData)
      setLastSync(new Date().toLocaleTimeString('en-US', { hour12: false }))

      if (hbResp.status === 'ok' && hbResp.config) {
        setHbConfig(hbResp.config)
      }
      if (fallbackResp.status === 'ok' && fallbackResp.config) {
        setFallbackConfig(fallbackResp.config)
      }
      if (incognitoResp.status === 'ok' && incognitoResp.config) {
        setIncognitoConfig(incognitoResp.config)
      }
    } catch (e) {
      console.error('Failed to fetch data:', e)
    } finally {
      setIsLoading(false)
    }
  }, [adminToken])

  useEffect(() => {
    refreshData()
    const interval = setInterval(refreshData, 30000)
    return () => clearInterval(interval)
  }, [refreshData])

  return {
    data,
    hbConfig,
    setHbConfig,
    fallbackConfig,
    setFallbackConfig,
    incognitoConfig,
    setIncognitoConfig,
    isLoading,
    lastSync,
    refreshData,
  }
}
