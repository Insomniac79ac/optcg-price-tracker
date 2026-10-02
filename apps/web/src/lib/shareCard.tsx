/* eslint-disable @next/next/no-img-element -- next/og requires native image elements. */
import type { CSSProperties, ReactNode } from "react";
export interface ShareCardContent {
  kind: "home" | "print" | "market" | "release";
  title: string; identity: string; value: string; context: string; date: string;
  code?: string; theme?: "straw-hat" | "marine" | "neutral"; faction?: string;
  movement?: { window: string; value: string }; artworks?: string[];
}
const ink = "#1b1c1b", paper = "#f1ecdf", teal = "#386e68";
const col: CSSProperties = { display: "flex", flexDirection: "column" };
const row: CSSProperties = { display: "flex", alignItems: "center" };
const serif: CSSProperties = { fontFamily: "Social Serif", fontWeight: 700 };
function Text({ children, style = {} }: { children: ReactNode; style?: CSSProperties }) { return <div style={{ display: "flex", ...style }}>{children}</div>; }
function Artwork({ src, height, width }: { src?: string; height: number; width: number }) {
  return src ? <img src={src} alt="" width={width} height={height} style={{ objectFit: "contain" }} /> : <div style={{ ...col, width, height, border: `1px solid ${ink}`, alignItems: "center", justifyContent: "center", fontSize: 18 }}>Artwork unavailable</div>;
}
function Fan({ images }: { images: string[] }) {
  // Side cards overlap as in the approved fan; every source is fitted in full.
  const slots = images.length >= 3 ? [1, 2, 0] : images.map((_, i) => i);
  return <div style={{ display: "flex", position: "relative", width: 602, height: 466, background: "#e2e5da", border: `3px solid ${ink}` }}>
    {slots.map((index, layer) => <div key={index} style={{ display: "flex", position: "absolute", left: images.length >= 3 ? [16, 363, 156][layer] : 145 + layer * 70, top: images.length >= 3 ? [75, 67, 20][layer] : 20, transform: images.length >= 3 ? ["rotate(-10deg)", "rotate(10deg)", "rotate(0deg)"][layer] : "rotate(0deg)" }}><Artwork src={images[index]} height={images.length >= 3 && layer < 2 ? 312 : 396} width={images.length >= 3 && layer < 2 ? 224 : 284} /></div>)}
    {!images.length && <Text style={{ margin: "auto", fontSize: 22 }}>One Piece card artwork unavailable</Text>}
    <Text style={{ position: "absolute", bottom: 0, left: 0, right: 0, height: 34, background: ink, color: paper, fontSize: 12, alignItems: "center", justifyContent: "center", letterSpacing: 2 }}>ONE PIECE · CARD ARTWORK</Text>
  </div>;
}
function Movement({ content }: { content: ShareCardContent }) {
  return content.movement ? <div style={{ ...row, gap: 16 }}><Text style={{ fontSize: 13, border: `1px solid ${ink}`, padding: "5px 9px" }}>{content.movement.window}</Text><Text style={{ ...serif, fontSize: 38 }}>{content.movement.value}</Text></div> : null;
}
export function ShareCard({ content: c }: { content: ShareCardContent }) {
  const images = c.artworks ?? [];
  const exact = c.kind === "print", home = c.kind === "home", release = c.kind === "release";
  const label = home ? "COLLECTION & MARKET" : exact ? "CARD VERSION / JAPAN" : release ? "SETS ON THE MOVE / JAPAN" : "MARKET / JAPAN";
  return <div style={{ ...col, width: 1200, height: 630, background: paper, color: ink, fontFamily: "Social Sans" }}>
    <div style={{ ...row, height: 80, padding: "0 34px", justifyContent: "space-between", background: ink, color: paper }}>
      <div style={{ ...row, gap: 24 }}><Text style={{ ...serif, fontSize: 30 }}>Card Pirate</Text><Text style={{ width: 130, fontSize: 11, lineHeight: 1.6, paddingLeft: 24, borderLeft: "1px solid #77766d", letterSpacing: 1 }}>INDEPENDENT CARD DATA</Text></div>
      <div style={{ ...col, alignItems: "flex-end", gap: 7 }}><Text style={{ fontSize: 13, fontWeight: 700, letterSpacing: 2 }}>ONE PIECE CARD PRICES</Text><Text style={{ fontSize: 10, letterSpacing: 1, color: "#bbb8b0" }}>{label}</Text></div>
    </div>
    {exact ? <div style={{ ...row, alignItems: "flex-start", height: 508, gap: 50, padding: "16px 34px" }}>
      <div style={{ ...col, width: 360, height: 476, flexShrink: 0, alignItems: "center", position: "relative", border: `1px solid ${ink}`, background: c.theme === "marine" ? "#dce3e5" : c.theme === "straw-hat" ? (c.code === "OP01-025" ? "#d9decb" : "#e3d4b4") : "#e2e5da" }}>
        <div style={{ position: "absolute", top: 6, right: 6, bottom: 6, left: 6, border: `1px solid ${ink}` }} />
        <Text style={{ ...serif, marginTop: 12, fontSize: 50, letterSpacing: 3 }}>{c.theme === "marine" ? "MARINE" : c.theme === "straw-hat" ? "WANTED" : "ONE PIECE"}</Text>
        <Text style={{ fontSize: 10, letterSpacing: 2, marginBottom: 10 }}>{c.faction}</Text>
        <Artwork src={images[0]} height={340} width={250} />
        <Text style={{ fontSize: 10, letterSpacing: 2, marginTop: 8 }}>{c.code}</Text>
      </div>
      <div style={{ ...col, flex: 1, paddingTop: 18 }}>
        <Text style={{ fontSize: 12, color: c.theme === "marine" ? "#28404e" : teal, letterSpacing: 2 }}>{c.faction}</Text>
        <Text style={{ ...serif, fontSize: c.title.length > 35 ? 37 : c.title.length > 22 ? 48 : 64, lineHeight: 1.06, marginTop: 20, minHeight: 130 }}>{c.title}</Text>
        <div style={{ ...row, gap: 16, marginTop: 8 }}><Text style={{ padding: "6px 10px", background: ink, color: paper, fontSize: 15 }}>{c.code}</Text><Text style={{ fontSize: 16 }}>{c.identity}</Text></div>
        <div style={{ ...col, marginTop: 24, paddingTop: 16, borderTop: `2px solid ${ink}` }}>
          <Text style={{ fontSize: 12, fontWeight: 700, letterSpacing: 1 }}>CARD PIRATE MARKET VALUE · ESTIMATE</Text>
          <Text style={{ ...serif, fontSize: c.value.length > 15 ? 40 : 60, marginTop: 4 }}>{c.value}</Text>
          <Text style={{ fontSize: 13, marginTop: 8 }}>{c.context}</Text>
        </div>
        <Text style={{ fontSize: 12, color: teal, marginTop: 18 }}>VIEW CARD →</Text>
      </div>
    </div> : home || release ? <div style={{ ...row, alignItems: "flex-start", height: 508, gap: 24, padding: "22px 34px" }}>
      <div style={{ ...col, width: 506, flexShrink: 0, paddingTop: 12 }}>
        <Text style={{ fontSize: 11, color: "#b9503e", letterSpacing: 2 }}>{home ? "YOUR ONE PIECE COLLECTION" : "SETS ON THE MOVE / JAPANESE EDITION"}</Text>
        {release && <Text style={{ fontSize: 16, marginTop: 18, fontWeight: 700 }}>{c.code}</Text>}
        <Text style={{ ...serif, fontSize: home ? 66 : c.title.length > 30 ? 39 : 51, lineHeight: 1.05, marginTop: 20, maxWidth: 465 }}>{home ? "Know what your cards are worth." : c.title}</Text>
        {home ? <div style={col}><Text style={{ fontSize: 21, lineHeight: 1.5, width: 430, marginTop: 24 }}>Prices for the cards you own, want and watch.</Text><Text style={{ fontSize: 11, borderTop: `2px solid ${ink}`, marginTop: 25, paddingTop: 17, letterSpacing: 1 }}>ONE PIECE CARDS · JAPANESE MARKET PRICES</Text></div> : <div style={col}>
          {c.movement && <div style={{ display: "flex", borderTop: `2px solid ${ink}`, borderBottom: "1px solid #999589", marginTop: 17, padding: "9px 0" }}><Movement content={c} /></div>}
          <Text style={{ fontSize: 11, letterSpacing: 1, marginTop: 18 }}>TRACKED CARD PIRATE MARKET VALUE</Text>
          <Text style={{ ...serif, fontSize: c.value.length > 15 ? 35 : 51, marginTop: 5 }}>{c.value}</Text>
          <Text style={{ fontSize: 13, lineHeight: 1.5, marginTop: 8 }}>{c.context}</Text>
          <Text style={{ fontSize: 12, color: teal, marginTop: 16 }}>SEE SET PRICES →</Text>
        </div>}
      </div>
      <Fan images={images} />
    </div> : <div style={{ ...col, height: 508, padding: "22px 34px" }}>
      <Text style={{ ...serif, fontSize: 42 }}>One Piece Market</Text>
      <div style={{ display: "flex", justifyContent: "space-between", marginTop: 17 }}><div style={col}>
        <Text style={{ fontSize: 12, fontWeight: 700, letterSpacing: 1 }}>CARD PIRATE MARKET VALUE</Text>
        <Text style={{ ...serif, fontSize: 57 }}>{c.value}</Text><Text style={{ fontSize: 14 }}>{c.context}</Text>
      </div><div style={{ ...col, width: 340, paddingLeft: 24, borderLeft: "1px solid #999589" }}><Movement content={c} />{c.movement && <Text style={{ fontSize: 12, marginTop: 8 }}>Comparable-card movement</Text>}</div></div>
      <div style={{ display: "flex", marginTop: 19, padding: 5, gap: 7, background: ink, height: 260 }}>
        {(images.length ? images : [undefined]).map((src, i) => <div key={i} style={{ display: "flex", flex: 1, alignItems: "center", justifyContent: "center", background: i === 2 ? "#dfe5e7" : "#e9e4d7", transform: "skew(-4deg)" }}><div style={{ display: "flex", transform: "skew(4deg)" }}><Artwork src={src} height={230} width={180} /></div></div>)}
      </div>
    </div>}
    <div style={{ ...col, height: 42, borderTop: "1px solid #999589", padding: "5px 34px", justifyContent: "space-between", fontSize: 10, color: "#494a43" }}>
      <Text>{c.date || "Japanese cards · Prices in JPY"}</Text>
      <Text>Card Pirate is independent. Not affiliated with Bandai, Shueisha or Toei Animation.</Text>
    </div>
  </div>;
}
