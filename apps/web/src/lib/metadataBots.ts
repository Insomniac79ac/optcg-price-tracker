// Reuse the pinned Next.js version's complete default list: a custom regex
// replaces it, so an AI-only override would regress existing social crawlers.
// This internal export is guarded by metadataBots.test.ts on Next upgrades.
import { HTML_LIMITED_BOT_UA_RE } from "next/dist/shared/lib/router/utils/html-bots";

// Documented at https://developers.openai.com/api/docs/bots.
// Rendering policy only; robots.ts separately controls crawler access.
export const metadataBlockingBots = new RegExp(
  `${HTML_LIMITED_BOT_UA_RE.source}|OAI-SearchBot|ChatGPT-User`,
  "i",
);
