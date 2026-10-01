/* eslint-disable @next/next/no-img-element -- next/og requires native image elements. */
import type { CSSProperties } from "react";
export interface ShareCardContent { kind: "home" | "print" | "market" | "release"; title: string; identity: string; value: string; context: string; date: string; artwork?: string | null; }
export function ShareCard({ content }: { content: ShareCardContent }) {
  const { kind, title, identity, value, context, date, artwork } = content;
  const column: CSSProperties = { display: "flex", flexDirection: "column" };
  return <div style={{ ...column, width: 1200, height: 630, padding: "44px 56px", background: "#10171b", color: "#edf1ee", fontFamily: "sans-serif", borderTop: "6px solid #b99a58" }}>
    <div style={{ display: "flex", flex: 1, gap: 48, alignItems: "center" }}>
      {artwork && <div style={{ display: "flex", width: 330, height: 465, flexShrink: 0, justifyContent: "center", alignItems: "center" }}>{/* Full source image, never cover/crop. */}<img src={artwork} alt="" width={330} height={465} style={{ objectFit: "contain" }} /></div>}
      <div style={{ ...column, flex: 1, minWidth: 0 }}>
        <div style={{ color: "#c6ad77", fontSize: 20, marginBottom: 18 }}>{kind === "print" ? "EXACT PRINT · JAPANESE CARD PRICES" : kind === "release" ? "RELEASE MARKET · JPY" : "ONE PIECE CARD PRICES"}</div>
        <div style={{ fontSize: kind === "home" ? 58 : 42, lineHeight: 1.1, fontWeight: 700 }}>{title}</div>
        <div style={{ fontSize: 21, color: "#aebfbe", marginTop: 14 }}>{identity}</div>
        <div style={{ fontSize: 46, color: "#e0bf77", marginTop: 28, fontWeight: 700 }}>{value}</div>
        <div style={{ fontSize: 22, lineHeight: 1.4, marginTop: 12 }}>{context}</div>
        <div style={{ fontSize: 18, color: "#aebfbe", marginTop: 16 }}>{date}</div>
      </div>
    </div>
    <div style={{ display: "flex", justifyContent: "space-between", borderTop: "1px solid #39423f", paddingTop: 16, fontSize: 19, color: "#aebfbe" }}><span style={{ color: "#d9be84" }}>CARD PIRATE</span><span>Market context for the cards you care about</span></div>
  </div>;
}
