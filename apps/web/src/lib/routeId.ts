import { NextResponse } from "next/server";

/** `[id]` segments are numeric database ids, and route handlers put them
 * straight into upstream API paths. Anything else (`..`, an encoded `/`)
 * could steer the request to another API path with the caller's own
 * credentials, so it gets a 404 before any upstream call (security audit
 * 2026-10-16, F8). */
const NUMERIC_ID = /^\d+$/;

export function isNumericRouteId(id: string): boolean {
  return NUMERIC_ID.test(id);
}

export function invalidRouteIdResponse(): NextResponse {
  return NextResponse.json({ error: "Not found" }, { status: 404 });
}
