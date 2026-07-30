import { describe, expect, it } from 'vitest'
import { compareVersions, normalizeVersion } from './version'

describe('semantic version helpers', () => {
  it.each([
    ['1.12.0', '1.12.0'],
    ['v1.12.0', '1.12.0'],
    ['V1.12.0-beta.2+build.7', '1.12.0-beta.2+build.7']
  ])('normalizes %s', (input, expected) => {
    expect(normalizeVersion(input)).toBe(expected)
  })

  it.each([
    ['1.12.0', 'v1.12.0', 0],
    ['1.13.0', '1.12.9', 1],
    ['2.0.0', '9.99.99', -1],
    ['1.12.0', '1.12.0-rc.1', 1],
    ['1.12.0-beta.10', '1.12.0-beta.2', 1],
    ['1.12.0-alpha', '1.12.0-beta', -1],
    ['1.12.0+build.2', '1.12.0+build.1', 0]
  ])('compares %s with %s', (left, right, expected) => {
    expect(compareVersions(left, right)).toBe(expected)
  })

  it.each([
    '',
    '1.2',
    '1.2.3.4',
    '01.2.3',
    '1.02.3',
    '1.2.03',
    '1.2.3-',
    '1.2.3-beta..1',
    'release-1.2.3'
  ])('rejects invalid version %s', (input) => {
    expect(normalizeVersion(input)).toBeNull()
    expect(compareVersions(input, '1.0.0')).toBeNull()
  })
})
