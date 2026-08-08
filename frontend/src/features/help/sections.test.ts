import { describe, expect, it } from 'vitest'
import { splitIntoSections } from './sections'

/**
 * The guide's own headings become the navigation, so the parsing has to
 * survive the things a real Markdown document contains — most importantly
 * shell commands, which are full of `#` comments.
 */
describe('splitIntoSections', () => {
  it('splits on top-level headings', () => {
    const sections = splitIntoSections('# One\n\nFirst.\n\n# Two\n\nSecond.\n')

    expect(sections.map((s) => s.title)).toEqual(['One', 'Two'])
    expect(sections[0].body).toContain('First.')
  })

  it('keeps the heading in the body so the section renders with its title', () => {
    const [section] = splitIntoSections('# Inbox\n\nText.\n')

    expect(section.body.startsWith('# Inbox')).toBe(true)
  })

  it('ignores a hash inside a fenced code block', () => {
    // Without this the guide's own shell examples would each start a
    // spurious section named after a comment.
    const sections = splitIntoSections(
      '# Real\n\n```bash\n# not a heading\nls\n```\n\n# Also real\n',
    )

    expect(sections.map((s) => s.title)).toEqual(['Real', 'Also real'])
  })

  it('keeps the preamble instead of discarding it', () => {
    // The preamble explains the callout conventions. A reader who never
    // sees it meets "Warning" and "Best Practice" with no key.
    const sections = splitIntoSections('Intro text.\n\n# One\n\nBody.\n')

    expect(sections[0].title).toBe('Overview')
    expect(sections[0].body).toContain('Intro text.')
  })

  it('drops sections that are only whitespace', () => {
    expect(splitIntoSections('\n\n   \n')).toEqual([])
  })

  it('gives every section a usable id', () => {
    const sections = splitIntoSections('# 4. Inbox & Conversations\n\nBody.\n')

    expect(sections[0].id).toBe('4-inbox-conversations')
  })

  it('handles Arabic headings', () => {
    const sections = splitIntoSections('# صندوق الوارد\n\nنص.\n')

    expect(sections[0].title).toBe('صندوق الوارد')
    expect(sections[0].id).not.toBe('')
  })
})
