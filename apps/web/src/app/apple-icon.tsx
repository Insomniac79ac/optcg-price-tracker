import { ImageResponse } from "next/og";

/** Apple touch icon - Next.js metadata-file convention, rendered at request
 * time via the built-in ImageResponse (no extra dependency, no binary asset
 * checked in). Kept deliberately simple (no clipped-corner card outline,
 * no route line) since the source detail is lost at 180px anyway - the
 * compass needle silhouette is what needs to read at a glance. */
export const size = { width: 180, height: 180 };
export const contentType = "image/png";

export default function AppleIcon() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "#171717",
          borderRadius: 32,
        }}
      >
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            width: 116,
            height: 144,
            borderRadius: 14,
            border: "4px solid #E8DEC7",
          }}
        >
          <div style={{ flex: 1 }} />
          <div
            style={{
              width: 0,
              height: 0,
              borderLeft: "20px solid transparent",
              borderRight: "20px solid transparent",
              borderBottom: "30px solid #C79A4B",
            }}
          />
          <div
            style={{
              width: 0,
              height: 0,
              borderLeft: "20px solid transparent",
              borderRight: "20px solid transparent",
              borderTop: "30px solid #4F8D86",
            }}
          />
          <div style={{ flex: 1 }} />
        </div>
      </div>
    ),
    { ...size },
  );
}
