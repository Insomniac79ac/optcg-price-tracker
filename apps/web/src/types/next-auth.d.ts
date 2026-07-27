import type { DefaultSession } from "next-auth";

declare module "next-auth" {
  interface Session {
    apiToken?: string;
    user?: DefaultSession["user"] & {
      id?: string;
      // Only ever "admin", for the temporary Credentials-based admin login
      // (see src/lib/auth.ts) - absent/undefined for every collector
      // (Google) session and for signed-out visitors. Never trust a role
      // read from anywhere other than this server-derived session object
      // (never from request headers, query strings, or form fields) - see
      // src/lib/adminSession.ts's requireAdminSession().
      role?: "admin";
    };
  }

  interface User {
    role?: "admin";
  }
}

declare module "next-auth/jwt" {
  interface JWT {
    role?: "admin";
    // Epoch-ms expiry for the `role` claim specifically, independent of
    // the underlying Auth.js session/cookie lifetime - see
    // ADMIN_SESSION_MAX_AGE_MS in src/lib/auth.ts.
    roleExpiresAt?: number;
  }
}
