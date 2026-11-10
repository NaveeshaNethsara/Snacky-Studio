import { describe, it, expect, vi } from 'vitest';
import { render } from '@testing-library/react';
import axe from 'axe-core';
import { BatchDownloader } from '@/components/BatchDownloader';
import { Library } from '@/components/Library';
import { PreferencesModal } from '@/components/PreferencesModal';
import { I18nProvider } from '@/lib/i18n';
import type { MediaFile } from '@/types';

// Mock files for testing library a11y
const mockFiles: MediaFile[] = [
  {
    filename: 'Sample Video [9f70c59c-0f10-4986-ae21-98f7675cf6ce].mp4',
    size: '12.4 MB',
    size_bytes: 13000000,
    created_at: 1700000000,
    format: 'mp4',
    kind: 'video',
  },
  {
    filename: 'Sample Audio [a26096ba-c687-443c-b604-78571de18049].mp3',
    size: '3.1 MB',
    size_bytes: 3200000,
    created_at: 1700050000,
    format: 'mp3',
    kind: 'audio',
  },
];

describe('Automated Accessibility (a11y) Audits with axe-core', () => {
  it('BatchDownloader has zero critical or serious WCAG accessibility violations', async () => {
    const { container } = render(
      <I18nProvider>
        <BatchDownloader
          busy={false}
          onBatchStarted={vi.fn()}
          onError={vi.fn()}
        />
      </I18nProvider>
    );

    const results = await axe.run(container, {
      runOnly: {
        type: 'tag',
        values: ['wcag2a', 'wcag2aa'],
      },
    });

    const criticalViolations = results.violations.filter(
      (v) => v.impact === 'critical' || v.impact === 'serious'
    );
    expect(criticalViolations).toEqual([]);
  });

  it('Library component has zero critical or serious WCAG accessibility violations', async () => {
    const { container } = render(
      <I18nProvider>
        <Library
          files={mockFiles}
          loading={false}
          onRefresh={vi.fn()}
          onSave={vi.fn()}
          onDelete={vi.fn()}
        />
      </I18nProvider>
    );

    const results = await axe.run(container, {
      runOnly: {
        type: 'tag',
        values: ['wcag2a', 'wcag2aa'],
      },
    });

    const criticalViolations = results.violations.filter(
      (v) => v.impact === 'critical' || v.impact === 'serious'
    );
    expect(criticalViolations).toEqual([]);
  });

  it('PreferencesModal has zero critical or serious WCAG accessibility violations', async () => {
    const { container } = render(
      <I18nProvider>
        <PreferencesModal
          open={true}
          onOpenChange={vi.fn()}
        />
      </I18nProvider>
    );

    const results = await axe.run(container, {
      runOnly: {
        type: 'tag',
        values: ['wcag2a', 'wcag2aa'],
      },
    });

    const criticalViolations = results.violations.filter(
      (v) => v.impact === 'critical' || v.impact === 'serious'
    );
    expect(criticalViolations).toEqual([]);
  });
});

