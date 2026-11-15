import { afterEach, expect, it } from 'vitest';
import { googleResultOf, resultMessages, takeGoogleResult } from './google-api';

afterEach(() => window.history.replaceState(null, '', '/'));

it('reads only the fixed result words', () => {
  for (const word of Object.keys(resultMessages)) {
    expect(googleResultOf(`?google=${word}`)).toBe(word);
  }
  expect(Object.keys(resultMessages).sort()).toEqual([
    'connected',
    'connected_earlier_not_revoked',
    'declined',
    'failed',
    'not_granted',
  ]);
});

it.each([
  '',
  '?google=',
  '?google=CONNECTED',
  '?google=connected%20',
  '?google=constructor',
  '?google=toString',
  '?google=__proto__',
  '?google=%3Cscript%3E',
  '?other=connected',
])('ignores anything else: %s', (search) => {
  expect(googleResultOf(search)).toBeNull();
});

it('takes the word out of the address bar and keeps the rest of the address', () => {
  window.history.replaceState(null, '', '/?google=declined&keep=1#part');
  expect(takeGoogleResult()).toBe('declined');
  expect(window.location.pathname + window.location.search + window.location.hash).toBe(
    '/?keep=1#part',
  );
  expect(takeGoogleResult()).toBeNull(); // read once
});

it('removes an unknown word as well, and reports nothing', () => {
  window.history.replaceState(null, '', '/?google=something-else');
  expect(takeGoogleResult()).toBeNull();
  expect(window.location.search).toBe('');
});

it('leaves an address without the parameter untouched', () => {
  window.history.replaceState(null, '', '/?keep=1');
  expect(takeGoogleResult()).toBeNull();
  expect(window.location.search).toBe('?keep=1');
});
