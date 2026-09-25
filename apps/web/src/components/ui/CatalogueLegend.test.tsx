import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, beforeEach, vi } from 'vitest';
import { CatalogueLegend } from './CatalogueLegend';
beforeEach(() => {
  HTMLDialogElement.prototype.showModal = vi.fn(function(this: HTMLDialogElement) { this.open=true; this.querySelector<HTMLElement>('button')?.focus(); });
  HTMLDialogElement.prototype.close = vi.fn(function(this: HTMLDialogElement) { this.open=false; });
});
function open() {
  const view=render(<div style={{transform:'translateZ(0)',zIndex:1}}><CatalogueLegend /><div style={{position:'relative',zIndex:999}}>Artwork</div></div>);
  const trigger=screen.getByRole('button',{name:/What do these labels mean/});
  trigger.focus(); fireEvent.click(trigger);
  return {...view,trigger,dialog:screen.getByRole('dialog',{name:'Catalogue terminology'})};
}
describe('catalogue terminology modal', () => {
  it('uses a portal and native modal top layer above artwork, with focus entering', () => {
    const {container,dialog}=open(); expect(container.contains(dialog)).toBe(false);
    expect(dialog.parentElement).toBe(document.body); expect(dialog.tagName).toBe('DIALOG');
    expect(HTMLDialogElement.prototype.showModal).toHaveBeenCalled();
    expect(screen.getByRole('button',{name:'Close catalogue terminology'})).toHaveFocus();
    expect(dialog).toHaveAttribute('aria-modal','true');
  });
  it('closes on native Escape cancel and restores focus', () => {
    const {dialog,trigger}=open(); fireEvent(dialog,new Event('cancel',{cancelable:true,bubbles:false}));
    expect(screen.queryByRole('dialog')).toBeNull(); expect(trigger).toHaveFocus();
  });
  it('closes on backdrop click and restores focus', () => {
    const {dialog,trigger}=open(); fireEvent.click(dialog);
    expect(screen.queryByRole('dialog')).toBeNull(); expect(trigger).toHaveFocus();
  });
  it('keeps content clicks open and definitions unchanged', () => {
    open(); fireEvent.click(screen.getByRole('heading',{name:'Rarity'}));
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    for (const name of ['Rarity','Special print','Printing']) expect(screen.getByRole('heading',{name})).toBeInTheDocument();
    for (const term of ['Alt Art','Reprint','SP Card','Treasure Rare','Found in']) expect(screen.getAllByText(term,{exact:false}).length).toBeGreaterThan(0);
  });
  it('uses viewport-bounded mobile presentation and locks only while open', () => {
    const {dialog}=open(); expect(dialog.className).toContain('max-h-[85dvh]'); expect(dialog.className).toContain('w-[calc(100%-2rem)]');
    expect(document.body.style.overflow).toBe('hidden'); fireEvent.click(dialog); expect(document.body.style.overflow).toBe('');
  });
});
