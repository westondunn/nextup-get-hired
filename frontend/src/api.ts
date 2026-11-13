export interface Diagnostic {
  id: string;
  source: 'manual' | 'scheduler';
  status: 'queued' | 'succeeded' | 'publish_failed' | 'failed';
  created_at: string;
  completed_at: string | null;
  worker: string | null;
  result: { message: string; database: string } | null;
  error_message?: string | null;
}

export interface Health {
  status: 'ok' | 'degraded';
  checks: Record<'api' | 'database' | 'broker' | 'worker', 'up' | 'down'>;
  scheduler: 'waiting' | 'recent delivery' | 'stale';
  diagnostic_interval_seconds: number;
  latest_diagnostic: Diagnostic | null;
  checked_at: string;
}

export async function readHealth(): Promise<Health> {
  const response = await fetch('/api/health', { signal: AbortSignal.timeout(15000) });
  const body = await response.json();
  if ((!response.ok && response.status !== 503) || !body.checks) {
    throw new Error('Status could not be read. Check the API and try again.');
  }
  return body;
}

export async function startDiagnostic(): Promise<Diagnostic> {
  const response = await fetch('/api/diagnostics', {
    method: 'POST',
    signal: AbortSignal.timeout(15000),
  });
  if (!response.ok) {
    const body = await response.json();
    if (response.status === 503 && typeof body.detail?.id === 'string') {
      return readDiagnostic(body.detail.id);
    }
    throw new Error('Diagnostic could not be queued. Check service status.');
  }
  return response.json();
}

export async function readDiagnostic(id: string): Promise<Diagnostic> {
  const response = await fetch(`/api/diagnostics/${id}`, { signal: AbortSignal.timeout(15000) });
  if (!response.ok) throw new Error('Diagnostic result could not be read.');
  return response.json();
}
