import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { releaseDisplayNameEnglish, releaseLabelEnglish } from './releaseNames';
import { releaseLabel } from './releases';
import { printFixture, releaseFixture } from './publicDiscoveryFixtures';
import { toPrintUiModel } from './prints';
import { ReleaseNavigation } from '@/components/ui/ReleaseNavigation';
import { PrintCardTile } from '@/components/ui/PrintCardTile';
import { AtlasReleaseDestination } from '@/components/ui/AtlasPrimitives';

describe('English release presentation', () => {
  it.each([['OP-17', "The World's Strongest Warriors"], ['OP-05', 'Awakening of the New Era']])('uses the official English title for %s', (code, name) => {
    expect(releaseDisplayNameEnglish(code)).toBe(name);
    render(<AtlasReleaseDestination releaseCode={code} href="/cards?release_product_id=186" />);
    expect(screen.getByText(name)).toBeInTheDocument();
  });
  it('does not invent a title or fall back to Japanese for unknown and uncoded products', () => {
    expect(releaseDisplayNameEnglish('UNKNOWN-99')).toBe('UNKNOWN-99');
    expect(releaseLabelEnglish('UNKNOWN-99')).toBe('UNKNOWN-99');
    expect(releaseDisplayNameEnglish(null)).toBe('Special product');
    expect(releaseLabel({ ...releaseFixture.items[0], official_code: null, display_name: '記念商品' })).toBe('Special product');
  });
  it('uses English strip/select labels without mutating source metadata, chronology or ID navigation', () => {
    const release = Object.freeze({ ...releaseFixture.items[0], display_name: '世界最強の戦士' });
    const onSelect = vi.fn();
    render(<ReleaseNavigation releases={[release]} selected={186} status="ready" hrefFor={(id) => `/cards?release_product_id=${id}`} onSelect={onSelect} onRetry={vi.fn()} />);
    const strip = within(screen.getByRole('navigation', { name: 'Browse releases' }));
    expect(strip.getByText("The World's Strongest Warriors")).toBeInTheDocument();
    expect(strip.queryByText(/世界最強の戦士/)).toBeNull();
    const option = screen.getByRole('option', { name: "OP-17 — The World's Strongest Warriors" });
    expect(option).toHaveValue('186');
    expect(option).not.toHaveTextContent('printings');
    const link = strip.getByRole('link', { name: "OP-17 — The World's Strongest Warriors" });
    expect(link).toHaveAttribute('href', '/cards?release_product_id=186');
    fireEvent.click(link); expect(onSelect).toHaveBeenLastCalledWith(186);
    fireEvent.change(screen.getByRole('combobox'), { target: { value: '186' } }); expect(onSelect).toHaveBeenLastCalledWith(186);
    expect(release.display_name).toBe('世界最強の戦士');
    expect(release.released_on).toBe('2026-08-22');
  });
  it.each(['世界最強の戦士', "The World's Strongest Warriors"])('keeps full title %s out of visible card tiles', (name) => {
    const source = printFixture(3686, { card_code: 'EB04-007', release_name: name });
    const print = toPrintUiModel(source);
    render(<PrintCardTile print={print} />);
    const tile = screen.getByRole('link');
    expect(tile).toHaveAttribute('href', '/prints/3686');
    expect(within(tile).getByText('Found in').parentElement).toHaveTextContent(/^Found in OP-17$/);
    expect(tile.textContent).not.toContain(name);
    expect(tile.textContent).not.toContain('Found in OP-17 —');
    expect(tile).toHaveAccessibleName(expect.stringContaining("OP-17 — The World's Strongest Warriors"));
    expect(within(tile).getByRole('img')).toHaveAttribute('loading', 'lazy');
    expect(print.releaseName).toBe(name); expect(source.release_product_id).toBe(186);
  });
});
