"use client";

import { useEffect, useState } from "react";

import { fetchVersionInfo, type VersionInfo } from "@/lib/api";

/** Small "web vX.Y.Z (commit) · api vX.Y.Z (commit)" line for admin pages -
 * see GET /api/version and docs/release_checklist.md. Silently renders
 * nothing if the version info can't be fetched, since this is a footnote,
 * not something worth an error state of its own. */
export function VersionFooter() {
  const [info, setInfo] = useState<VersionInfo | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchVersionInfo()
      .then((data) => {
        if (!cancelled) setInfo(data);
      })
      .catch(() => {
        if (!cancelled) setInfo(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!info) return null;

  return (
    <p className="mt-8 text-[11px] text-neutral-600">
      web v{info.web.version}
      {info.web.git_commit !== "unknown" ? ` (${info.web.git_commit})` : ""}
      {info.api
        ? ` · api v${info.api.version}${
            info.api.git_commit !== "unknown" ? ` (${info.api.git_commit})` : ""
          }`
        : ""}
    </p>
  );
}
