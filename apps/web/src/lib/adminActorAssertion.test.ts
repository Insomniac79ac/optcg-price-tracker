// @vitest-environment node
import { readFileSync } from "node:fs";

import { decodeJwt, jwtVerify } from "jose";
import { describe, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));

import {
  ADMIN_ACTOR_AUDIENCE,
  ADMIN_ACTOR_ISSUER,
  ADMIN_ACTOR_PURPOSE,
  deriveAdminActorKey,
  digestAdminActorBody,
  signAdminActorAssertion,
} from "./adminActorAssertion";

const vector = JSON.parse(
  readFileSync(new URL("../../../../docs/contracts/admin-actor-assertion-v1.json", import.meta.url), "utf8"),
);

describe("admin actor assertion contract", () => {
  it("matches the shared cross-language key and body digest vector", async () => {
    expect(Buffer.from(deriveAdminActorKey(vector.admin_token)).toString("hex")).toBe(
      vector.derived_key_hex,
    );
    expect(digestAdminActorBody(Buffer.from(vector.body_utf8))).toBe(vector.body_sha256);
    const verified = await jwtVerify(vector.jwt, deriveAdminActorKey(vector.admin_token), {
      algorithms: ["HS256"],
      issuer: vector.claims.issuer,
      audience: vector.claims.audience,
      currentDate: new Date(vector.claims.issued_at * 1000),
    });
    expect(verified.payload.purpose).toBe(vector.claims.purpose);
  });

  it("signs a sixty-second identity and request-bound HS256 assertion", async () => {
    const body = Buffer.from(vector.body_utf8);
    const token = await signAdminActorAssertion({
      adminToken: vector.admin_token,
      identity: { id: vector.claims.subject, email: vector.claims.email },
      method: vector.claims.method,
      path: vector.claims.path,
      body,
      nowSeconds: vector.claims.issued_at,
      jti: vector.claims.jti,
    });
    const header = JSON.parse(Buffer.from(token.split(".")[0], "base64url").toString());
    const claims = decodeJwt(token);
    expect(header.alg).toBe("HS256");
    expect(claims).toMatchObject({
      iss: ADMIN_ACTOR_ISSUER,
      aud: ADMIN_ACTOR_AUDIENCE,
      purpose: ADMIN_ACTOR_PURPOSE,
      sub: vector.claims.subject,
      email: vector.claims.email,
      method: vector.claims.method,
      path: vector.claims.path,
      body_sha256: vector.body_sha256,
      iat: vector.claims.issued_at,
      exp: vector.claims.expiry,
      jti: vector.claims.jti,
    });
  });
});
