import { expect, it } from 'vitest';
import { parseDelimited } from './csv';

it('reads comma-separated text with quoted cells', () => {
  expect(
    parseDelimited(
      'Title,Company,Notes\r\n"Manager, Operations",Acme,"said ""hello""\nsecond line"\n\n',
    ),
  ).toEqual([
    ['Title', 'Company', 'Notes'],
    ['Manager, Operations', 'Acme', 'said "hello"\nsecond line'],
  ]);
});

it('reads tab-separated text when the header has a tab', () => {
  expect(parseDelimited('Title\tCompany\nManager, Operations\tAcme')).toEqual([
    ['Title', 'Company'],
    ['Manager, Operations', 'Acme'],
  ]);
});

it('returns nothing for empty text', () => {
  expect(parseDelimited('')).toEqual([]);
  expect(parseDelimited('\n \n')).toEqual([]);
});
