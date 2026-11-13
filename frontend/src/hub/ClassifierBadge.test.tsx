import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import { ClassifierBadge, type ImportedMessage } from './MessageCard';

afterEach(cleanup);

const message = (detection: ImportedMessage['detection'], classifier_company?: string | null) =>
  ({
    source: 'gmail',
    channel: 'email',
    direction: 'inbound',
    sender: 'Riley <riley@example.test>',
    subject: 'Hello',
    body: 'Hi',
    received_at: null,
    detection,
    classifier_company,
  }) as ImportedMessage;

const hint = {
  classification: 'opportunity' as const,
  companies: ['Harlow Northwind Corp'],
  company_id: 'c1',
  company_name: 'Harlow Northwind (old name)',
  confidence: 0.91,
  model: 'example-model',
  prompt_version: 'p1',
  classified_at: null,
  agrees: null,
};

it('shows the classification with the current company name and no warning when Nextup has no opinion', () => {
  render(
    <ClassifierBadge message={message({ kind: 'none', classifier: hint }, 'Harlow Northwind')} />,
  );
  const badge = screen.getByText('Classifier: Opportunity · Harlow Northwind');
  expect(badge.getAttribute('title')).toContain('example-model (91%)');
  expect(screen.queryByText('Classifier disagrees')).toBeNull();
});

it('flags a disagreement and explains which reading Nextup used', () => {
  render(
    <ClassifierBadge
      message={message({
        kind: 'application_confirmation',
        classifier: { ...hint, classification: 'not_relevant', company_id: null, agrees: false },
      })}
    />,
  );
  expect(screen.getByText('Classifier: Not relevant · Harlow Northwind (old name)')).toBeTruthy();
  expect(screen.getByText('Classifier disagrees').getAttribute('title')).toBe(
    "Nextup read this as an application confirmation; the classifier said Not relevant. Nextup's reading is used.",
  );
});

it('renders nothing for mail the classifier has not seen', () => {
  const { container } = render(<ClassifierBadge message={message({ kind: 'none' })} />);
  expect(container.innerHTML).toBe('');
});
