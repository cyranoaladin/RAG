// @vitest-environment jsdom

import { act } from 'react'
import { hydrateRoot, type Root } from 'react-dom/client'
import { renderToString } from 'react-dom/server'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { useIsMobile } from './use-mobile'

let matchMediaWindow: Window | undefined
let matchMediaDescriptor: PropertyDescriptor | undefined

function MobileProbe() {
  return <span>{useIsMobile() ? 'mobile' : 'desktop'}</span>
}

function createMatchMedia(initialMatches: boolean) {
  let matches = initialMatches
  const listeners = new Set<() => void>()
  const media = '(max-width: 767px)'
  const mediaQuery = {
    get matches() {
      return matches
    },
    media,
    onchange: null,
    addEventListener: vi.fn((_type: string, listener: () => void) => {
      listeners.add(listener)
    }),
    removeEventListener: vi.fn((_type: string, listener: () => void) => {
      listeners.delete(listener)
    }),
  } as unknown as MediaQueryList

  return {
    mediaQuery,
    setMatches(nextMatches: boolean) {
      matches = nextMatches
      listeners.forEach((listener) => listener())
    },
  }
}

describe('useIsMobile', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    if (matchMediaWindow) {
      if (matchMediaDescriptor) {
        Object.defineProperty(
          matchMediaWindow,
          'matchMedia',
          matchMediaDescriptor,
        )
      } else {
        Reflect.deleteProperty(matchMediaWindow, 'matchMedia')
      }
    }
    matchMediaWindow = undefined
    matchMediaDescriptor = undefined
    document.body.replaceChildren()
  })

  it('hydrate le snapshot serveur puis suit les changements du média', async () => {
    const browserWindow = window
    matchMediaWindow = browserWindow
    matchMediaDescriptor = Object.getOwnPropertyDescriptor(
      browserWindow,
      'matchMedia',
    )
    const { mediaQuery, setMatches } = createMatchMedia(true)
    Object.defineProperty(browserWindow, 'matchMedia', {
      configurable: true,
      value: vi.fn(() => mediaQuery),
    })

    vi.stubGlobal('window', undefined)
    const serverMarkup = renderToString(<MobileProbe />)
    vi.stubGlobal('window', browserWindow)

    const container = document.createElement('div')
    container.innerHTML = serverMarkup
    document.body.append(container)
    const hydrationErrors: unknown[] = []
    let root: Root | undefined

    await act(async () => {
      root = hydrateRoot(container, <MobileProbe />, {
        onRecoverableError: (error) => hydrationErrors.push(error),
      })
    })

    expect(hydrationErrors).toEqual([])
    expect(container.textContent).toBe('mobile')

    act(() => setMatches(false))
    expect(container.textContent).toBe('desktop')

    await act(async () => root?.unmount())
    expect(mediaQuery.removeEventListener).toHaveBeenCalledOnce()
  })
})
