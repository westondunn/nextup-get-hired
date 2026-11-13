import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import MessageCard, { MessageBody, groupThreads, replySubject } from './MessageCard';

const long = 'Line of a long recruiter message that must stay complete.\n'.repeat(60);

describe('MessageCard', () => {
  it('shows every character of the message body', () => {
    render(<MessageBody body={long} />);
    expect(
      screen.getByText((_, el) => el?.tagName === 'PRE' && el.textContent === long),
    ).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Show without scrolling' })).toBeTruthy();
  });

  it('renders sender, subject, source and the full body without a toggle for short mail', () => {
    render(
      <MessageCard
        heading="Message to answer"
        message={{
          source: 'gmail',
          channel: 'email',
          direction: 'inbound',
          sender: 'Sam <sam@example.com>',
          subject: 'Are you available?',
          body: 'Hi Alex, can we talk Friday?',
          received_at: '2026-10-20T15:00:00Z',
        }}
      />,
    );
    expect(screen.getByText('Message to answer')).toBeTruthy();
    expect(screen.getByText('Sam <sam@example.com>')).toBeTruthy();
    expect(screen.getByText('email')).toBeTruthy();
    expect(screen.getByText('Are you available?')).toBeTruthy();
    expect(screen.getByText('Hi Alex, can we talk Friday?')).toBeTruthy();
    expect(screen.queryByRole('button')).toBeNull();
  });

  it('groups a Gmail thread oldest-first and orders threads by latest activity', () => {
    const base = {
      source: 'gmail',
      channel: 'email',
      direction: 'inbound',
      sender: null,
      body: '',
    };
    const rows = [
      { ...base, id: 'a', subject: 'A', thread_id: 't1', received_at: '2026-10-01T00:00:00Z' },
      { ...base, id: 'b', subject: 'B', thread_id: null, received_at: '2026-10-02T00:00:00Z' },
      { ...base, id: 'c', subject: 'C', thread_id: 't1', received_at: '2026-10-03T00:00:00Z' },
    ];
    const threads = groupThreads(rows);
    expect(threads.map((t) => t.map((m) => m.id))).toEqual([['a', 'c'], ['b']]);
  });

  it('prefixes a reply subject once', () => {
    expect(replySubject('Alex, are you available?')).toBe('Re: Alex, are you available?');
    expect(replySubject('RE: already')).toBe('RE: already');
    expect(replySubject('')).toBe('Re:');
  });
});
