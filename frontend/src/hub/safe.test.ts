import { expect, it } from 'vitest';
import { localDate, safeHref } from './safe';

it('formats the local calendar date, not the UTC one', () => {
  // Local midnight is the previous day in UTC for every zone east of Greenwich.
  expect(localDate(new Date(2026, 0, 5, 0, 0, 0))).toBe('2026-01-05');
  expect(localDate(new Date(2026, 11, 31, 23, 59, 59))).toBe('2026-12-31');
  expect(localDate(new Date('2026-03-09T00:00:00'))).toBe('2026-03-09');
});

it('only follows http and https links', () => {
  expect(safeHref('https://jobs.example/role/1')).toBe('https://jobs.example/role/1');
  expect(safeHref('http://jobs.example')).toBe('http://jobs.example');
  for (const bad of [
    'javascript:alert(1)',
    'data:text/html,x',
    'file:///etc/passwd',
    'jobs.example',
    '',
    null,
    undefined,
  ]) {
    expect(safeHref(bad)).toBeUndefined();
  }
});
