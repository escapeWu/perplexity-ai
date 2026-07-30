interface ParsedVersion {
  major: number
  minor: number
  patch: number
  prerelease: string[]
  build: string[]
}

const CORE_VERSION_PATTERN = /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/
const IDENTIFIER_PATTERN = /^[0-9A-Za-z-]+$/

function parseIdentifiers(
  value: string | undefined,
  rejectNumericLeadingZero: boolean
): string[] | null {
  if (value === undefined) return []

  const identifiers = value.split('.')
  if (
    identifiers.some(
      (identifier) =>
        !identifier ||
        !IDENTIFIER_PATTERN.test(identifier) ||
        (rejectNumericLeadingZero &&
          /^\d+$/.test(identifier) &&
          identifier.length > 1 &&
          identifier.startsWith('0'))
    )
  ) {
    return null
  }

  return identifiers
}

function parseVersion(value: string): ParsedVersion | null {
  const trimmed = value.trim().replace(/^[vV]/, '')
  if (!trimmed) return null

  const plusIndex = trimmed.indexOf('+')
  const versionAndPrerelease =
    plusIndex === -1 ? trimmed : trimmed.slice(0, plusIndex)
  const buildValue = plusIndex === -1 ? undefined : trimmed.slice(plusIndex + 1)
  if (plusIndex !== -1 && buildValue?.includes('+')) return null

  const dashIndex = versionAndPrerelease.indexOf('-')
  const core =
    dashIndex === -1
      ? versionAndPrerelease
      : versionAndPrerelease.slice(0, dashIndex)
  const prereleaseValue =
    dashIndex === -1 ? undefined : versionAndPrerelease.slice(dashIndex + 1)

  const coreMatch = CORE_VERSION_PATTERN.exec(core)
  if (!coreMatch) return null

  const prerelease = parseIdentifiers(prereleaseValue, true)
  const build = parseIdentifiers(buildValue, false)
  if (prerelease === null || build === null) return null

  const [major, minor, patch] = coreMatch.slice(1).map(Number)
  if (![major, minor, patch].every(Number.isSafeInteger)) return null

  return { major, minor, patch, prerelease, build }
}

function comparePrerelease(left: string[], right: string[]): number {
  if (left.length === 0 && right.length === 0) return 0
  if (left.length === 0) return 1
  if (right.length === 0) return -1

  for (let index = 0; index < Math.max(left.length, right.length); index++) {
    const leftIdentifier = left[index]
    const rightIdentifier = right[index]

    if (leftIdentifier === undefined) return -1
    if (rightIdentifier === undefined) return 1
    if (leftIdentifier === rightIdentifier) continue

    const leftIsNumeric = /^\d+$/.test(leftIdentifier)
    const rightIsNumeric = /^\d+$/.test(rightIdentifier)
    if (leftIsNumeric && rightIsNumeric) {
      if (leftIdentifier.length !== rightIdentifier.length) {
        return leftIdentifier.length > rightIdentifier.length ? 1 : -1
      }
      return leftIdentifier > rightIdentifier ? 1 : -1
    }
    if (leftIsNumeric) return -1
    if (rightIsNumeric) return 1
    return leftIdentifier > rightIdentifier ? 1 : -1
  }

  return 0
}

export function normalizeVersion(value: string): string | null {
  const parsed = parseVersion(value)
  if (!parsed) return null

  const prerelease =
    parsed.prerelease.length > 0 ? `-${parsed.prerelease.join('.')}` : ''
  const build = parsed.build.length > 0 ? `+${parsed.build.join('.')}` : ''
  return `${parsed.major}.${parsed.minor}.${parsed.patch}${prerelease}${build}`
}

/**
 * Compare two strict semantic versions.
 *
 * Returns 1 when left is newer, -1 when right is newer, 0 when they have the
 * same precedence, and null when either input is not a valid semantic version.
 */
export function compareVersions(
  leftValue: string,
  rightValue: string
): number | null {
  const left = parseVersion(leftValue)
  const right = parseVersion(rightValue)
  if (!left || !right) return null

  for (const field of ['major', 'minor', 'patch'] as const) {
    if (left[field] > right[field]) return 1
    if (left[field] < right[field]) return -1
  }

  return comparePrerelease(left.prerelease, right.prerelease)
}
