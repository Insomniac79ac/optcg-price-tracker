import NextAuth from "next-auth";
import Google from "next-auth/providers/google";
import { SignJWT } from "jose";

const API_JWT_TTL = "1h";

function apiJwtSecretKey(): Uint8Array {
  const secret = process.env.API_JWT_SECRET;
  if (!secret) {
    throw new Error("API_JWT_SECRET is not configured");
  }
  return new TextEncoder().encode(secret);
}

export const { handlers, auth, signIn, signOut } = NextAuth({
  providers: [Google],
  session: { strategy: "jwt" },
  // Vercel sets the incoming request's Host header safely (it can't be
  // spoofed by the client - Vercel's edge network overwrites it), so
  // trusting it here is the documented-safe case, not a host-header-
  // injection risk. Without this, proxy.ts's `auth()` wrapper throws
  // UntrustedHost internally (see https://errors.authjs.dev#untrustedhost)
  // and - critically - fails *open*: the protected route it's wrapping
  // renders normally instead of redirecting to /sign-in. Reproduced
  // locally via `next start` (which lacks Vercel's auto-detection) while
  // investigating why proxy.ts wasn't gating /collection etc. in staging.
  trustHost: true,
  callbacks: {
    async jwt({ token, profile }) {
      // `profile` is only present on the initial sign-in request - carry the
      // Google account's stable id/email/name/picture forward into every
      // subsequent token refresh.
      if (profile) {
        token.sub = profile.sub as string;
        token.email = profile.email as string;
        token.name = profile.name as string | undefined;
        token.picture = profile.picture as string | undefined;
      }
      return token;
    },
    async session({ session, token }) {
      // Mints a short-lived, separately-signed bearer token for the
      // FastAPI backend (which lives on a different host/domain and can't
      // easily verify NextAuth's own encrypted session JWE) - see
      // docs/deployment.md for the full rationale. Session-only; never
      // persisted anywhere besides the client's in-memory session object.
      const apiToken = await new SignJWT({
        email: token.email as string,
        name: token.name as string | undefined,
      })
        .setProtectedHeader({ alg: "HS256" })
        .setSubject(token.sub as string)
        .setIssuedAt()
        .setExpirationTime(API_JWT_TTL)
        .sign(apiJwtSecretKey());

      session.apiToken = apiToken;
      if (session.user) {
        session.user.id = token.sub as string;
      }
      return session;
    },
  },
});
