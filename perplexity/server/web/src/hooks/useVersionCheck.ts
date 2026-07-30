import { useState, useEffect } from 'react'
import { compareVersions, normalizeVersion } from 'lib/version'

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

interface CachedRelease {
  schema: 2
  repository: string
  checkedAt: number
  release: ReleaseInfo
}

const LEGACY_CACHE_KEY = 'perplexity_version_check'
const CACHE_KEY = 'perplexity_version_check:v2'
const CACHE_DURATION = 60 * 60 * 1000 // 1 hour
const REQUEST_TIMEOUT = 8000

function getRepositorySlug(repoUrl: string): string | null {
  try {
    const url = new URL(repoUrl)
    if (url.protocol !== 'https:' || url.hostname !== 'github.com') return null

    const [owner, rawRepository] = url.pathname.split('/').filter(Boolean)
    const repository = rawRepository?.replace(/\.git$/, '')
    if (
      !owner ||
      !repository ||
      !/^[0-9A-Za-z_.-]+$/.test(owner) ||
      !/^[0-9A-Za-z_.-]+$/.test(repository)
    ) {
      return null
    }
    return `${owner}/${repository}`
  } catch {
    return null
  }
}

function isReleaseInfo(value: unknown): value is ReleaseInfo {
  if (!value || typeof value !== 'object') return false
  const release = value as Partial<ReleaseInfo>
  if (
    typeof release.tag_name !== 'string' ||
    release.tag_name.length > 100 ||
    typeof release.html_url !== 'string'
  ) {
    return false
  }

  try {
    const releaseUrl = new URL(release.html_url)
    return (
      releaseUrl.protocol === 'https:' &&
      releaseUrl.hostname === 'github.com' &&
      releaseUrl.pathname.includes('/releases/')
    )
  } catch {
    return false
  }
}

function readCachedRelease(repository: string): CachedRelease | null {
  try {
    const raw = localStorage.getItem(CACHE_KEY)
    if (!raw) return null

    const cached = JSON.parse(raw) as Partial<CachedRelease>
    if (
      cached.schema !== 2 ||
      cached.repository !== repository ||
      typeof cached.checkedAt !== 'number' ||
      !Number.isFinite(cached.checkedAt) ||
      !isReleaseInfo(cached.release)
    ) {
      localStorage.removeItem(CACHE_KEY)
      return null
    }
    return cached as CachedRelease
  } catch {
    try {
      localStorage.removeItem(CACHE_KEY)
    } catch {
      // Version checks must not break when storage is unavailable.
    }
    return null
  }
}

function writeCachedRelease(cache: CachedRelease): void {
  try {
    localStorage.setItem(CACHE_KEY, JSON.stringify(cache))
  } catch {
    // The update reminder still works when storage is full or unavailable.
  }
}

function resultFromRelease(
  release: ReleaseInfo,
  error = false
): VersionCheckResult | null {
  const latestVersion = normalizeVersion(release.tag_name)
  const currentVersion = normalizeVersion(CURRENT_VERSION)
  const comparison = compareVersions(release.tag_name, CURRENT_VERSION)
  if (!latestVersion || !currentVersion || comparison === null) return null

  return {
    hasUpdate: comparison > 0,
    latestVersion: `v${latestVersion}`,
    releaseUrl: release.html_url,
    loading: false,
    error
  }
}

function initialResult(error = false): VersionCheckResult {
  const currentVersion = normalizeVersion(CURRENT_VERSION) || CURRENT_VERSION
  return {
    hasUpdate: false,
    latestVersion: `v${currentVersion}`,
    releaseUrl: '',
    loading: false,
    error
  }
}

export const useVersionCheck = (): VersionCheckResult => {
  const [result, setResult] = useState<VersionCheckResult>({
    hasUpdate: false,
    latestVersion: `v${normalizeVersion(CURRENT_VERSION) || CURRENT_VERSION}`,
    releaseUrl: '',
    loading: true,
    error: false
  })

  useEffect(() => {
    let active = true
    const controller = new AbortController()
    const timeoutId = window.setTimeout(
      () => controller.abort(),
      REQUEST_TIMEOUT
    )

    const checkVersion = async () => {
      const repository = getRepositorySlug(REPO_URL)
      if (!repository) {
        if (active) setResult(initialResult(true))
        return
      }

      try {
        localStorage.removeItem(LEGACY_CACHE_KEY)
      } catch {
        // Ignore storage failures and continue with the network request.
      }

      let cached = readCachedRelease(repository)
      const cacheAge = cached ? Date.now() - cached.checkedAt : null
      if (cached && cacheAge !== null && cacheAge < 0) {
        cached = null
        try {
          localStorage.removeItem(CACHE_KEY)
        } catch {
          // Ignore storage failures and continue with the network request.
        }
      }
      if (
        cached &&
        cacheAge !== null &&
        cacheAge >= 0 &&
        cacheAge < CACHE_DURATION
      ) {
        const cachedResult = resultFromRelease(cached.release)
        if (cachedResult) {
          if (active) setResult(cachedResult)
          return
        }
        cached = null
        try {
          localStorage.removeItem(CACHE_KEY)
        } catch {
          // Ignore storage failures and continue with the network request.
        }
      }

      try {
        const response = await fetch(
          `https://api.github.com/repos/${repository}/releases/latest`,
          {
            headers: {
              Accept: 'application/vnd.github+json',
              'X-GitHub-Api-Version': '2022-11-28'
            },
            signal: controller.signal
          }
        )
        if (!response.ok) {
          throw new Error(`GitHub release check failed: ${response.status}`)
        }

        const release: unknown = await response.json()
        if (!isReleaseInfo(release)) {
          throw new Error('GitHub release response is invalid')
        }

        const newResult = resultFromRelease(release)
        if (!newResult) {
          throw new Error(`Invalid release version: ${release.tag_name}`)
        }

        writeCachedRelease({
          schema: 2,
          repository,
          checkedAt: Date.now(),
          release
        })
        if (active) setResult(newResult)
      } catch (err) {
        if (!active) return

        const fallbackResult = cached
          ? resultFromRelease(cached.release, true)
          : null
        setResult(fallbackResult || initialResult(true))
        if (!(err instanceof DOMException && err.name === 'AbortError')) {
          console.warn('Version check failed:', err)
        }
      }
    }

    void checkVersion().finally(() => window.clearTimeout(timeoutId))
    return () => {
      active = false
      window.clearTimeout(timeoutId)
      controller.abort()
    }
  }, [])

  return result
}
