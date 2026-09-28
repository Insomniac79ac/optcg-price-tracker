import { fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { releaseFixture } from "@/lib/publicDiscoveryFixtures";
import { ReleaseSelector } from "./ReleaseSelector";
import { CollectorMultiSelect } from "./CollectorMultiSelect";

const op17 = "OP-17 — The World's Strongest Warriors";
const op16 = "OP-16 — THE TIME OF BATTLE";
function Selector({ initial = null, changed = () => {} }: { initial?: number | null; changed?: (id: number | null) => void }) {
  const [selected, setSelected] = useState(initial);
  return <ReleaseSelector releases={releaseFixture.items} selected={selected} onChange={(id) => { changed(id); setSelected(id); }} />;
}
const trigger = () => screen.getByRole("button", { name: /^Release / });
const open = () => fireEvent.click(trigger());

describe("Release collector control", () => {
  it("shares the collector trigger structure and styling with a concise empty summary", () => {
    render(<><Selector /><CollectorMultiSelect label="Rarity" options={["SR"]} selected={[]} onChange={vi.fn()} /></>);
    const release = trigger();
    expect(release).toHaveAccessibleName("Release All releases");
    expect(release.className).toBe(screen.getByRole("button", { name: "Rarity Any" }).className);
    expect(Array.from(release.children).map(child => child.textContent)).toEqual(["Release", "All releases", "⌄"]);
    expect(release).toHaveAttribute("aria-haspopup", "dialog");
    expect(release).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });

  it("keeps the selected summary short and shows the full English name in the popover", () => {
    render(<ReleaseSelector releases={releaseFixture.items.map(item => ({ ...item, display_name: "世界最強の戦士" }))} selected={186} onChange={vi.fn()} />);
    expect(trigger()).toHaveAccessibleName("Release OP-17");
    expect(trigger()).not.toHaveTextContent("World's Strongest");
    open();
    expect(screen.getByRole("radio", { name: op17 })).toBeChecked();
    expect(document.body).not.toHaveTextContent("世界最強の戦士");
    expect(trigger()).toHaveAttribute("aria-controls", screen.getByRole("dialog", { name: "Release options" }).id);
  });

  it.each(["OP-17", "world's strongest", "  World's Strongest  "])("searches the loaded labels for %s without changing selection", (query) => {
    const changed = vi.fn();
    render(<Selector changed={changed} />);
    open();
    const search = screen.getByRole("searchbox", { name: "Search release options" });
    expect(search).toHaveFocus();
    fireEvent.change(search, { target: { value: query } });
    expect(screen.getAllByRole("radio")).toHaveLength(2);
    expect(screen.getByRole("radio", { name: "All releases" })).toBeChecked();
    expect(screen.getByRole("radio", { name: op17 })).toBeInTheDocument();
    expect(changed).not.toHaveBeenCalled();
  });

  it("uses one native radio group and replaces the previous release immediately", () => {
    const changed = vi.fn();
    render(<Selector changed={changed} />);
    open();
    const group = screen.getByRole("radiogroup", { name: "Release" });
    expect(new Set(within(group).getAllByRole("radio").map(radio => radio.getAttribute("name"))).size).toBe(1);
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("radio", { name: op17 }));
    fireEvent.click(screen.getByRole("radio", { name: op16 }));
    expect(changed.mock.calls).toEqual([[186], [185]]);
    expect(within(group).getAllByRole("radio", { checked: true })).toEqual([screen.getByRole("radio", { name: op16 })]);
    expect(trigger()).toHaveAccessibleName("Release OP-16");
    expect(trigger()).toHaveAttribute("aria-expanded", "true");
  });

  it.each(["Clear release", "All releases"])("clears selection using %s", (name) => {
    const changed = vi.fn();
    render(<Selector initial={186} changed={changed} />);
    open();
    fireEvent.click(screen.getByRole(name === "All releases" ? "radio" : "button", { name }));
    expect(changed).toHaveBeenCalledExactlyOnceWith(null);
    expect(trigger()).toHaveAccessibleName("Release All releases");
    expect(screen.getByRole("radio", { name: "All releases" })).toBeChecked();
    expect(screen.getByRole("button", { name: "Clear release" })).toBeDisabled();
  });

  it("opens with ArrowDown, closes with Escape/Done/outside click, and restores focus", () => {
    render(<Selector />);
    const button = trigger();
    button.focus();
    fireEvent.keyDown(button, { key: "ArrowDown" });
    expect(screen.getByRole("searchbox")).toHaveFocus();
    fireEvent.keyDown(document.activeElement!, { key: "Escape" });
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(button).toHaveFocus();
    open();
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(button).toHaveFocus();
    open();
    fireEvent.pointerDown(document.body);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(button).toHaveFocus();
  });

  it("shows an empty search state and resets search when reopened", () => {
    render(<Selector />);
    open();
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "no such release" } });
    expect(screen.getByText("No matching releases")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "All releases" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    open();
    expect(screen.getByRole("searchbox")).toHaveValue("");
    expect(screen.getByRole("radio", { name: op17 })).toBeInTheDocument();
  });

  it("retains an unavailable selected ID without inventing a release label", () => {
    const changed = vi.fn();
    render(<ReleaseSelector releases={[]} selected={999} onChange={changed} />);
    expect(trigger()).toHaveAccessibleName("Release Selected release");
    open();
    expect(screen.getByRole("radio", { name: "Selected release" })).toBeChecked();
    expect(changed).not.toHaveBeenCalled();
  });
});
