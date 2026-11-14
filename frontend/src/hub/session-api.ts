import { request } from '../jobs-api';

// Local session for integration settings (docs/decisions/0001-local-session-boundary.md).
// The session itself is an HttpOnly cookie the browser sends on its own; nothing here
// stores the setup code or a session identifier.
export interface SessionState {
  configured: boolean;
  active: boolean;
}

export const readSession = () => request<SessionState>('session');
export const startSession = (code: string) =>
  request<void>('session', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code }),
  });
export const endSession = () => request<void>('session', { method: 'DELETE' });
