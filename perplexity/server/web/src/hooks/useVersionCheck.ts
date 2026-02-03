import { useState, useEffect } from 'react'

const REPO_URL = __REPO_URL__
const CURRENT_VERSION = __APP_VERSION__

interface ReleaseInfo {
  tag_name: string
  html_url: string
}

interface VersionCheckResult {
  hasUpdate: boolean
  latestVersion: string
  releaseUrl: string
  loading: boolean
  error: boolean
}

const CACHE_KEY = 'perplexity_version_check'
const CACHE_DURATION = 60 * 60 * 1000 // 1 hour

export const useVersionCheck = (): VersionCheckResult => {
  const [result, setResult] = useState<VersionCheckResult>({
    hasUpdate: false,
    latestVersion: CURRENT_VERSION,
    releaseUrl: '',
    loading: true,
    error: false,
  })

  useEffect(() => {
    const checkVersion = async () => {
      try {
        // Parse owner and repo from URL
        // Expected format: https://github.com/owner/repo
        const match = REPO_URL.match(/github\.com\/([^/]+)\/([^/]+)/)
        if (!match) {
          throw new Error('Invalid repo URL')
        }
        const [, owner, repo] = match
        const apiUrl = `https://api.github.com/repos/${owner}/${repo}/releases/latest`

        // Check cache
        const cached = localStorage.getItem(CACHE_KEY)
        if (cached) {
          const { timestamp, data } = JSON.parse(cached)
          if (Date.now() - timestamp < CACHE_DURATION) {
            setResult(data)
            return
          }
        }

        const response = await fetch(apiUrl)
        if (!response.ok) {
          throw new Error('Failed to fetch version')
        }

        const data: ReleaseInfo = await response.json()
        const latestVersion = data.tag_name.replace(/^v/, '') // Remove 'v' prefix if present

        // Simple version comparison (assuming semver)
        const hasUpdate = compareVersions(latestVersion, CURRENT_VERSION) > 0

        const newResult = {
          hasUpdate,
          latestVersion: data.tag_name,
          releaseUrl: data.html_url,
          loading: false,
          error: false,
        }

        // Update cache
        localStorage.setItem(CACHE_KEY, JSON.stringify({
          timestamp: Date.now(),
          data: newResult
        }))

        setResult(newResult)
      } catch (err) {
        console.error('Version check failed:', err)
        setResult(prev => ({ ...prev, loading: false, error: true }))
      }
    }

    checkVersion()
  }, [])

  return result
}

// Returns 1 if v1 > v2, -1 if v1 < v2, 0 if equal
function compareVersions(v1: string, v2: string): number {
  const parts1 = v1.split('.').map(Number)
  const parts2 = v2.split('.').map(Number)

  for (let i = 0; i < Math.max(parts1.length, parts2.length); i++) {
    const p1 = parts1[i] || 0
    const p2 = parts2[i] || 0
    if (p1 > p2) return 1
    if (p1 < p2) return -1
  }

  return 0
}
