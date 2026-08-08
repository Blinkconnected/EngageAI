import { describe, expect, it } from 'vitest'
import en from '../../locales/en/search.json'
import ar from '../../locales/ar/search.json'
import { SEARCH_ENTITY_TYPE_ORDER, SEARCH_RESULT_PATHS, type SearchEntityType } from './types'

/**
 * The entity type list is a contract with the backend, and every entry
 * needs three things here: a place in the render order, a route (or an
 * explicit `null`), and a label in both languages.
 *
 * Miss the order entry and the type's results are silently dropped —
 * `grouped` filters by it, so the backend returns matches the dialog
 * never shows. Miss a label and the group heading renders as the raw
 * key. Neither fails the build, and neither is visible until somebody
 * happens to search for the right thing.
 */
const groupLabels = en.GlobalSearchDialog.groupLabels as Record<string, string>
const arabicGroupLabels = ar.GlobalSearchDialog.groupLabels as Record<string, string>

describe('search entity types', () => {
  it('has a route decision for every type in the render order', () => {
    for (const type of SEARCH_ENTITY_TYPE_ORDER) {
      expect(SEARCH_RESULT_PATHS).toHaveProperty(type)
    }
  })

  it('renders every type it knows how to route', () => {
    // `Record<SearchEntityType, …>` forces the paths map to be complete,
    // so it is the authority on which types exist. Anything in it but
    // missing from the order is a match the dialog would discard.
    const routed = Object.keys(SEARCH_RESULT_PATHS) as SearchEntityType[]
    expect([...SEARCH_ENTITY_TYPE_ORDER].sort()).toEqual([...routed].sort())
  })

  it('labels every type in English and in Arabic', () => {
    for (const type of SEARCH_ENTITY_TYPE_ORDER) {
      expect(groupLabels[type], `no English label for ${type}`).toBeTruthy()
      expect(arabicGroupLabels[type], `no Arabic label for ${type}`).toBeTruthy()
    }
  })

  it('carries no label for a type that is never returned', () => {
    // A leftover label is dead weight nobody thinks to delete, and it
    // hides the fact that the type stopped being searched.
    expect(Object.keys(groupLabels).sort()).toEqual([...SEARCH_ENTITY_TYPE_ORDER].sort())
  })
})
