import '@testing-library/jest-dom/vitest'
import { Storage } from 'happy-dom'

// Node 24's optional native storage must not replace the browser test double.
Object.defineProperty(globalThis, 'localStorage', {
  configurable: true,
  value: new Storage()
})
Object.defineProperty(globalThis, 'sessionStorage', {
  configurable: true,
  value: new Storage()
})
