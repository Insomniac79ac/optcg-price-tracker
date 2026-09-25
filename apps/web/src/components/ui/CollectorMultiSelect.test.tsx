import { fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useState } from 'react';
import { CollectorMultiSelect } from './CollectorMultiSelect';
import { PrintCatalogueToolbar } from './PrintCatalogueToolbar';
import { EMPTY_PRINT_FILTERS, type PrintCatalogueFilters } from '@/lib/catalogueState';

const changed = vi.fn();
const facets = { rarities: ['SR', 'SEC', 'R'], treatments: ['normal', 'parallel'], languages: ['jp'], verification_statuses: ['verified'] };
const matchMedia = window.matchMedia;
function Toolbar({ initial = EMPTY_PRINT_FILTERS }: { initial?: PrintCatalogueFilters }) {
  const [filters, setFilters] = useState(initial);
  return <PrintCatalogueToolbar filters={filters} facets={facets} onChange={(value) => { changed(value); setFilters(value); }} />;
}
beforeEach(() => {
  changed.mockReset();
  HTMLDialogElement.prototype.showModal = vi.fn(function(this: HTMLDialogElement) { this.open = true; this.querySelector<HTMLElement>('button')?.focus(); });
  HTMLDialogElement.prototype.close = vi.fn(function(this: HTMLDialogElement) { this.open = false; });
});
afterEach(() => { window.matchMedia = matchMedia; });
const openRarity = () => fireEvent.click(screen.getByRole('button', { name: /^Rarity/ }));

describe('compact desktop collector filters', () => {
  it('is initially closed, exposes multi-selection and updates its closed summary', () => {
    render(<Toolbar />);
    const trigger = screen.getByRole('button', { name: 'Rarity Any' });
    expect(trigger).toHaveAttribute('aria-expanded', 'false'); expect(screen.queryByRole('checkbox')).toBeNull();
    openRarity(); expect(trigger).toHaveAttribute('aria-expanded', 'true');
    fireEvent.click(screen.getByRole('checkbox', { name: 'Super Rare' }));
    fireEvent.click(screen.getByRole('checkbox', { name: 'Secret Rare' }));
    expect(screen.getByRole('checkbox', { name: 'Super Rare' })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: 'Secret Rare' })).toBeChecked();
    expect(changed).toHaveBeenLastCalledWith(expect.objectContaining({ rarities: ['SR', 'SEC'] }));
    expect(changed).toHaveBeenCalledTimes(2);
    fireEvent.click(screen.getByRole('button', { name: 'Done' }));
    expect(screen.getByRole('button', { name: 'Rarity 2 selected' })).toHaveAttribute('aria-expanded', 'false');
    expect(trigger).toHaveFocus(); expect(screen.queryByRole('checkbox')).toBeNull();
  });
  it('opens from the keyboard, focuses an option, and restores focus on Escape/outside dismissal', () => {
    render(<Toolbar />); const trigger = screen.getByRole('button', { name: 'Rarity Any' }); trigger.focus();
    fireEvent.keyDown(trigger, { key: 'ArrowDown' });
    expect(screen.getByRole('checkbox', { name: 'Super Rare' })).toHaveFocus();
    fireEvent.keyDown(document.activeElement!, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).toBeNull(); expect(trigger).toHaveFocus();
    openRarity(); fireEvent.pointerDown(document.body);
    expect(screen.queryByRole('dialog')).toBeNull(); expect(trigger).toHaveFocus();
  });
  it('clears one category, and Clear collector filters preserves release/search/sort context', () => {
    render(<Toolbar initial={{ ...EMPTY_PRINT_FILTERS, releaseProductId: 186, q: 'Luffy', sort: 'created_desc', rarities: ['SR', 'SEC'], treatments: ['parallel'] }} />);
    openRarity(); fireEvent.click(screen.getByRole('button', { name: 'Clear rarity' }));
    expect(changed).toHaveBeenLastCalledWith(expect.objectContaining({ rarities: [], treatments: ['parallel'], releaseProductId: 186, q: 'Luffy', sort: 'created_desc' }));
    fireEvent.click(screen.getByRole('button', { name: 'Done' }));
    fireEvent.click(screen.getByRole('button', { name: 'Clear collector filters' }));
    expect(changed).toHaveBeenLastCalledWith(expect.objectContaining({ rarities: [], treatments: [], releaseProductId: 186, q: 'Luffy', sort: 'created_desc' }));
    expect(screen.getByRole('heading', { name: 'Collector filters' })).toBeInTheDocument();
  });
  it.each([{ releaseProductId: 186 }, { q: 'Luffy' }])('does not count browse context %o', (context) => {
    render(<Toolbar initial={{ ...EMPTY_PRINT_FILTERS, ...context }} />);
    expect(screen.getByRole('heading', { name: 'Collector filters' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Clear collector filters' })).toBeNull();
  });
  it('adds search only for a long option family and retains selected options', () => {
    const options = ['C', 'L', 'P', 'R', 'SEC', 'SP CARD', 'SR', 'TR', 'UC'];
    const { container } = render(<CollectorMultiSelect label="Rarity" options={options} selected={['SR']} onChange={changed} />);
    openRarity(); const search = screen.getByRole('searchbox', { name: 'Search rarity options' });
    expect(search).toHaveFocus();
    expect(screen.getAllByRole('checkbox')).toHaveLength(9);
    expect(container.querySelector('[role="group"]')?.className).toContain('options');
    fireEvent.change(search, { target: { value: 'SEC' } });
    fireEvent.click(screen.getByRole('checkbox', { name: 'SEC' }));
    expect(changed).toHaveBeenLastCalledWith(['SR', 'SEC']);
    fireEvent.change(search, { target: { value: 'no such value' } });
    expect(screen.getByText('No matching options')).toBeInTheDocument();
  });
  it('does not add a search field for short option lists', () => {
    render(<Toolbar />); openRarity(); expect(screen.queryByRole('searchbox')).toBeNull();
  });
});

describe('mobile compact draft filters', () => {
  beforeEach(() => { window.matchMedia = vi.fn().mockImplementation((query) => ({ matches: query.includes('max-width'), addEventListener: vi.fn(), removeEventListener: vi.fn() })); });
  it('edits both dropdowns without committing, then applies exactly once', () => {
    render(<Toolbar initial={{ ...EMPTY_PRINT_FILTERS, releaseProductId: 186 }} />);
    fireEvent.click(screen.getByRole('button', { name: 'Filters' }));
    const sheet = screen.getByRole('dialog', { name: 'Filters' });
    expect(within(sheet).queryByRole('checkbox')).toBeNull();
    openRarity();
    for (const name of ['Super Rare', 'Secret Rare']) fireEvent.click(screen.getByRole('checkbox', { name }));
    fireEvent.keyDown(document.activeElement!, { key: 'Escape' });
    expect(sheet).toBeInTheDocument(); expect(screen.getByRole('button', { name: 'Rarity 2 selected' })).toHaveFocus();
    fireEvent.click(screen.getByRole('button', { name: 'Treatment Any' }));
    for (const name of ['normal', 'parallel']) fireEvent.click(screen.getByRole('checkbox', { name }));
    fireEvent.click(screen.getByRole('button', { name: 'Done' }));
    expect(changed).not.toHaveBeenCalled();
    fireEvent.click(within(sheet).getByRole('button', { name: 'Apply filters' }));
    expect(changed).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({ releaseProductId: 186, rarities: ['SR', 'SEC'], treatments: ['normal', 'parallel'] }));
    expect(screen.queryByRole('dialog')).toBeNull();
  });
  it('clears the entire draft only on Apply', () => {
    render(<Toolbar initial={{ ...EMPTY_PRINT_FILTERS, releaseProductId: 186, q: 'Luffy', rarities: ['SR'], treatments: ['parallel'] }} />);
    fireEvent.click(screen.getByRole('button', { name: 'Filters · 2' }));
    fireEvent.click(screen.getByRole('button', { name: 'Clear all' }));
    expect(changed).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Rarity Any' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Apply filters' }));
    expect(changed).toHaveBeenCalledExactlyOnceWith(EMPTY_PRINT_FILTERS);
  });
});
