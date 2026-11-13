import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import StageSuggestions from './StageSuggestions';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const suggestion = {
  stage: 'interview',
  pursuit_id: 'p1',
  current_stage: 'applied',
  company: 'Acme',
  title: 'Director QE',
  evidence: 'phone interview',
  communication: {
    id: 'c1',
    source: 'gmail',
    sender: 'Riley <riley@acme.example>',
    subject: 'Availability for a phone interview',
    body: 'Are you free Tuesday?',
    received_at: '2026-11-10T15:00:00Z',
    created_at: '2026-11-10T15:00:00Z',
  },
};

it('shows a suggestion, reveals the whole message, and confirms it with one click', async () => {
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(new Response(JSON.stringify([suggestion])))
    .mockResolvedValueOnce(new Response(JSON.stringify({ decision: 'applied' })))
    .mockResolvedValueOnce(new Response('[]'));
  vi.stubGlobal('fetch', fetch);
  const onChanged = vi.fn();
  render(<StageSuggestions onChanged={onChanged} />);

  expect(await screen.findByText(/reads like an interview for Director QE at Acme/)).toBeTruthy();
  expect(screen.queryByText('Are you free Tuesday?')).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'Read message' }));
  expect(screen.getByText('Are you free Tuesday?')).toBeTruthy();

  fireEvent.click(screen.getByRole('button', { name: 'Move from applied to interview' }));
  await waitFor(() => expect(onChanged).toHaveBeenCalled());
  expect(fetch.mock.calls[1][0]).toBe('/api/communications/c1/stage-suggestion');
  expect(JSON.parse(fetch.mock.calls[1][1].body)).toEqual({ decision: 'apply' });
  expect(screen.getByText(/moved to interview. A preparation task was added/)).toBeTruthy();
});

it('renders nothing when there are no suggestions', async () => {
  const fetch = vi.fn().mockResolvedValue(new Response('[]'));
  vi.stubGlobal('fetch', fetch);
  const { container } = render(<StageSuggestions />);
  await waitFor(() => expect(fetch).toHaveBeenCalled());
  expect(container.innerHTML).toBe('');
});
