import "server-only";

import { createHash, randomUUID } from "node:crypto";
import { SignJWT } from "jose";

import type { AdminIdentity } from "@/lib/adminSession";

export const ADMIN_ACTOR_ISSUER = "opcg-web-admin-proxy";
export const ADMIN_ACTOR_AUDIENCE = "opcg-proposal-decision";
export const ADMIN_ACTOR_PURPOSE = "approve_exact_proposal";
export const ADMIN_ACTOR_MAX_LIFETIME_SECONDS = 60;
const KEY_DOMAIN = Buffer.from("opcg-admin-actor-v1\0", "utf8");

export function deriveAdminActorKey(adminToken: string): Uint8Array {
  return createHash("sha256").update(KEY_DOMAIN).update(adminToken, "utf8").digest();
}

export function digestAdminActorBody(body: Uint8Array): string {
  return createHash("sha256").update(body).digest("hex");
}

interface SignAdminActorAssertionOptions {
  adminToken: string;
  identity: AdminIdentity;
  method: string;
  path: string;
  body: Uint8Array;
  nowSeconds?: number;
  jti?: string;
}

export async function signAdminActorAssertion({
  adminToken,
  identity,
  method,
  path,
  body,
  nowSeconds = Math.floor(Date.now() / 1000),
  jti = randomUUID(),
}: SignAdminActorAssertionOptions): Promise<string> {
  return new SignJWT({
    purpose: ADMIN_ACTOR_PURPOSE,
    email: identity.email,
    method: method.toUpperCase(),
    path,
    body_sha256: digestAdminActorBody(body),
  })
    .setProtectedHeader({ alg: "HS256", typ: "JWT" })
    .setIssuer(ADMIN_ACTOR_ISSUER)
    .setAudience(ADMIN_ACTOR_AUDIENCE)
    .setSubject(identity.id)
    .setIssuedAt(nowSeconds)
    .setExpirationTime(nowSeconds + ADMIN_ACTOR_MAX_LIFETIME_SECONDS)
    .setJti(jti)
    .sign(deriveAdminActorKey(adminToken));
}
