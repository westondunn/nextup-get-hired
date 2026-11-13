export interface HistoryPreview {
  enabled: boolean;
  retention_days: number;
  batch_size: number;
  cutoff: string;
  expires_at: string;
  token: string;
  groups: Record<
    'diagnostics' | 'fetches',
    {
      eligible: number;
      selected: number;
      items: { id: string; source: string; status: string; completed_at: string }[];
    }
  >;
}

export interface CleanupResult {
  groups: Record<'diagnostics' | 'fetches', { deleted: number; skipped: number }>;
}

export async function previewHistory(): Promise<HistoryPreview> {
  const response = await fetch('/api/task-history/preview', { signal: AbortSignal.timeout(15000) });
  if (!response.ok) throw new Error('Preview unavailable. Check service status and try again.');
  return response.json();
}

export async function cleanupHistory(token: string): Promise<CleanupResult> {
  let response: Response;
  try {
    response = await fetch('/api/task-history/cleanup', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token, confirmation: 'delete_completed_task_history' }),
      signal: AbortSignal.timeout(15000),
    });
  } catch {
    throw new Error('Cleanup was not confirmed. Preview again to see what remains.');
  }
  if (!response.ok) {
    throw new Error(
      response.status === 409
        ? 'Preview expired or changed. Preview cleanup again.'
        : response.status === 403
          ? 'Cleanup is disabled in local configuration.'
          : 'Cleanup was not confirmed. Preview again to see what remains.',
    );
  }
  return response.json();
}
