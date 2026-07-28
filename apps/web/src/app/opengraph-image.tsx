import { ImageResponse } from "next/og";

import { brand } from "@/lib/brand";

/** Social-sharing card - Next.js metadata-file convention, rendered at
 * request time via ImageResponse (ships with Next.js, no new dependency
 * and no binary asset to keep in sync with the brand copy). Uses the
 * platform's default font rather than fetching Fraunces at request time,
 * a deliberate simplification to avoid an extra runtime font fetch for a
 * single social-preview surface. */
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function OpengraphImage() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          padding: "0 96px",
          background: "#171717",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 28 }}>
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              width: 84,
              height: 104,
              borderRadius: 12,
              border: "4px solid #E8DEC7",
            }}
          >
            <div style={{ flex: 1 }} />
            <div
              style={{
                width: 0,
                height: 0,
                borderLeft: "15px solid transparent",
                borderRight: "15px solid transparent",
                borderBottom: "22px solid #C79A4B",
              }}
            />
            <div
              style={{
                width: 0,
                height: 0,
                borderLeft: "15px solid transparent",
                borderRight: "15px solid transparent",
                borderTop: "22px solid #4F8D86",
              }}
            />
            <div style={{ flex: 1 }} />
          </div>
          <div style={{ display: "flex", flexDirection: "column" }}>
            <div style={{ fontSize: 64, fontWeight: 700, color: "#F4F0E8" }}>
              {brand.productName}
            </div>
            <div
              style={{
                fontSize: 22,
                fontWeight: 600,
                letterSpacing: 2,
                textTransform: "uppercase",
                color: "#8B8672",
                marginTop: 6,
              }}
            >
              {brand.endorsementLine}
            </div>
          </div>
        </div>
        <div
          style={{
            display: "flex",
            fontSize: 34,
            color: "#4F8D86",
            marginTop: 48,
            maxWidth: 980,
          }}
        >
          {brand.tagline}
        </div>
      </div>
    ),
    { ...size },
  );
}
