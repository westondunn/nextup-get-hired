import { describe, expect, it } from 'vitest';
import { composeWithEvidence, renderResumeBody, renderResumeHtml } from './resume-print';

describe('renderResumeBody', () => {
  it('maps headings, bullets and paragraphs and escapes HTML', () => {
    const html = renderResumeBody(
      '# Alex <Rivera>\nExample City\n\n## Experience\n- Led QE & platform\n* Cut escapes 40%\nSummary line',
    );
    expect(html).toBe(
      [
        '<h1>Alex &lt;Rivera&gt;</h1>',
        '<p>Example City</p>',
        '<h2>Experience</h2>',
        '<ul>',
        '<li>Led QE &amp; platform</li>',
        '<li>Cut escapes 40%</li>',
        '</ul>',
        '<p>Summary line</p>',
      ].join('\n'),
    );
  });

  it('keeps consecutive text lines in one paragraph', () => {
    expect(renderResumeBody('Acme | Director\n2020 – 2024')).toBe(
      '<p>Acme | Director<br>2020 – 2024</p>',
    );
  });

  it('wraps the body in a printable document with an escaped title', () => {
    const html = renderResumeHtml('QE "Lead"', '# Name');
    expect(html).toContain('<title>QE &quot;Lead&quot;</title>');
    expect(html).toContain('@page');
    expect(html).toContain('<h1>Name</h1>');
  });
});

describe('composeWithEvidence', () => {
  it('appends new bullets under one heading and skips duplicates', () => {
    const once = composeWithEvidence('# Name\n- Already there', ['Already there', 'New win']);
    expect(once).toBe('# Name\n- Already there\n\n## Selected achievements\n- New win\n');
    const twice = composeWithEvidence(once, ['New win', 'Second win']);
    expect(twice).toBe(`${once.trimEnd()}\n- Second win\n`);
    expect(composeWithEvidence(twice, ['Second win'])).toBe(twice);
  });
});
