export interface GuideSection {
  id: string
  title: string
  /** The section's Markdown, heading included. */
  body: string
}

/**
 * Splits the guide into its top-level sections.
 *
 * The guide's `# ` headings are its table of contents, so they are also
 * the navigation here. Parsing them at read time rather than serving the
 * document pre-chunked means adding a section to the file is the whole
 * job — no endpoint to change, nothing to keep in step.
 *
 * Everything before the first `# ` heading (title, contents, how-to-read)
 * becomes an "Overview" section rather than being dropped: it is the part
 * that explains the callouts, and a reader landing in the middle of a
 * document with unexplained conventions is worse off than one who saw
 * them.
 */
export function splitIntoSections(markdown: string): GuideSection[] {
  const lines = markdown.split('\n')
  const sections: GuideSection[] = []
  let current: { title: string; lines: string[] } | null = null
  let inFence = false

  for (const line of lines) {
    // A `# ` inside a fenced code block is a shell comment, not a
    // heading. Without this the guide's own command examples would each
    // start a spurious section.
    if (line.startsWith('```')) inFence = !inFence

    if (!inFence && line.startsWith('# ')) {
      if (current) sections.push(toSection(current))
      current = { title: line.slice(2).trim(), lines: [line] }
      continue
    }
    if (current) current.lines.push(line)
    else {
      current = { title: '', lines: [line] }
    }
  }
  if (current) sections.push(toSection(current))

  return sections
    .map((section, index) =>
      section.title === '' ? { ...section, id: `overview-${index}`, title: 'Overview' } : section,
    )
    .filter((section) => section.body.trim() !== '')
}

function toSection(raw: { title: string; lines: string[] }): GuideSection {
  return {
    id: slugify(raw.title) || 'overview',
    title: raw.title,
    body: raw.lines.join('\n').trim(),
  }
}

function slugify(title: string): string {
  return title
    .toLowerCase()
    .replace(/[^a-z0-9؀-ۿ ]+/g, '')
    .trim()
    .replace(/\s+/g, '-')
}
