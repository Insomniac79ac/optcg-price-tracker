import { describe, expect, it } from "vitest";
import { HTML_LIMITED_BOT_UA_RE } from "next/dist/shared/lib/router/utils/html-bots";
import { shouldServeStreamingMetadata } from "next/dist/server/lib/streaming-metadata";
import { PHASE_PRODUCTION_SERVER } from "next/constants";
import config from "../../next.config";

describe("metadata rendering in the installed Next version", () => {
  const pattern = config(PHASE_PRODUCTION_SERVER).htmlLimitedBots!.source;
  it("preserves the entire framework default expression", () => {
    expect(pattern).toContain(HTML_LIMITED_BOT_UA_RE.source);
  });
  it.each(["Mozilla/5.0 Chrome/140.0 Safari/537.36", "Mozilla/5.0 (iPhone) AppleWebKit/605.1.15 Version/18.0 Mobile Safari/604.1", "Googlebot/2.1"])("allows metadata streaming for %s", (ua) => {
    expect(shouldServeStreamingMetadata(ua, pattern)).toBe(true);
    expect(shouldServeStreamingMetadata(ua, ".*")).toBe(false);
  });
  it.each(["OAI-SearchBot/1.3", "ChatGPT-User/1.0", "Twitterbot/1.0", "facebookexternalhit/1.1", "Slackbot-LinkExpanding 1.0", "Bingbot/2.0", "Discordbot/2.0", "LinkedInBot/1.0"])("blocks for head-readable metadata for %s", (ua) => {
    expect(shouldServeStreamingMetadata(ua, pattern)).toBe(false);
  });
  it("does not treat GPTBot training policy as search or expand it", () => {
    expect(shouldServeStreamingMetadata("GPTBot/1.0", pattern)).toBe(true);
  });
});
