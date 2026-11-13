/** Deterministic, local rendering of resume text for the browser's print-to-PDF. */

const escapeHtml = (value: string) =>
  value.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

/**
 * Lines starting with `#`, `##`, `###` become headings, `- ` or `* ` become bullets,
 * blank lines separate paragraphs, and consecutive text lines stay in one paragraph.
 */
export function renderResumeBody(text: string): string {
  const out: string[] = [];
  let paragraph: string[] = [];
  let inList = false;
  const flush = () => {
    if (paragraph.length) {
      out.push(`<p>${paragraph.map(escapeHtml).join('<br>')}</p>`);
      paragraph = [];
    }
    if (inList) {
      out.push('</ul>');
      inList = false;
    }
  };
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trimEnd();
    const heading = /^(#{1,3})\s+(.*)$/.exec(line);
    const bullet = /^[-*]\s+(.*)$/.exec(line);
    if (!line.trim()) {
      flush();
    } else if (heading) {
      flush();
      const level = heading[1].length;
      out.push(`<h${level}>${escapeHtml(heading[2])}</h${level}>`);
    } else if (bullet) {
      if (paragraph.length) {
        out.push(`<p>${paragraph.map(escapeHtml).join('<br>')}</p>`);
        paragraph = [];
      }
      if (!inList) {
        out.push('<ul>');
        inList = true;
      }
      out.push(`<li>${escapeHtml(bullet[1])}</li>`);
    } else {
      if (inList) {
        out.push('</ul>');
        inList = false;
      }
      paragraph.push(line);
    }
  }
  flush();
  return out.join('\n');
}

export function renderResumeHtml(title: string, text: string): string {
  return `<!doctype html>
<html><head><meta charset="utf-8"><title>${escapeHtml(title)}</title>
<style>
  @page { margin: 0.6in; }
  body { font: 10.5pt/1.35 Georgia, 'Times New Roman', serif; color: #111; max-width: 7.3in; margin: 0 auto; }
  h1 { font-size: 18pt; margin: 0 0 2pt; letter-spacing: 0.02em; }
  h2 { font-size: 11pt; text-transform: uppercase; letter-spacing: 0.08em; border-bottom: 1px solid #333; margin: 12pt 0 4pt; padding-bottom: 2pt; }
  h3 { font-size: 10.5pt; margin: 8pt 0 2pt; }
  p { margin: 0 0 4pt; }
  ul { margin: 0 0 4pt 1.1em; padding: 0; }
  li { margin: 0 0 2pt; }
</style></head>
<body>
${renderResumeBody(text)}
</body></html>
`;
}

/** Append chosen evidence bullets under one heading, skipping lines already present. */
export function composeWithEvidence(base: string, bullets: string[]): string {
  const existing = new Set(base.split(/\r?\n/).map((line) => line.replace(/^[-*]\s+/, '').trim()));
  const fresh = bullets.map((b) => b.trim()).filter((b) => b && !existing.has(b));
  if (!fresh.length) return base;
  const heading = '## Selected achievements';
  const body = fresh.map((b) => `- ${b}`).join('\n');
  if (base.includes(heading)) return `${base.trimEnd()}\n${body}\n`;
  return `${base.trimEnd()}\n\n${heading}\n${body}\n`;
}
