# PR #11 admin shell drift after manual review

Manual review on immutable deployment `dpl_5iqJYWu2iQjqfyd9y6NJtQGVbnpU`
(`c40ba3d8ac1d422215af82e5510f2a9cedb91849`) failed. The reviewer saw
the protected Admin overview body on the immutable host, with public navigation,
Sign in, a broken legacy image logo, and no grouped admin rail. This was not a
successful authenticated visual review.

## Read-only diagnosis

- The protected layout calls `requireAdminSession()` before rendering the page.
  A visible Admin overview therefore establishes that the server-side auth
  boundary accepted the request on the immutable deployment host. The
  screenshot also confirms that the browser stayed on that host.
- The previous `AppShell` required `useSession().user.role === "admin"` to
  render the admin rail. The previous `TopBar` independently required a client
  admin session to use the Atlas admin treatment. The Sign in button in the
  screenshot corresponds to `TopBar`'s unauthenticated client-session branch;
  loading alone would have shown an ellipsis. This is a direct server/client
  shell disagreement.
- A read-only Vercel request-log query for that deployment returned 23
  `GET /api/auth/session` requests with HTTP 200 on the immutable hostname. It
  also showed a credentials callback with HTTP 200 and four `/admin` requests
  with HTTP 200. No MissingSecret, UntrustedHost, or session error marker
  appeared in the inspected log messages. The browser's session fetch did
  reach the immutable host; a cross-host fetch and an HTTP error are not
  supported by these logs.
- Vercel request logs do not contain the session response body or Set-Cookie
  headers. They cannot distinguish an active session from an empty response,
  prove when the cookie was issued, or establish whether the client state was
  stale after login. No cookie, token, email, or secret was read. The
  server-authorized page shows that a usable server session existed for those
  `/admin` requests, but it does not establish what `useSession()` received.
- A separate unauthenticated GET made through Vercel CLI's existing protection
  bypass to the immutable deployment returned HTTP 307 from `/admin` to
  `/admin/login` on **the stable staging host**. The detail route did the same
  while preserving its callback path. This was a real host bug, independent of
  the rail drift, and explains how navigation could leave the immutable URL.
  Auth.js's `reqWithEnvURL` replaces `req.nextUrl`'s origin with the configured
  `AUTH_URL`; the proxy used that rewritten origin to construct the login
  redirect. No response body, cookie, or credential was read by this check.

The confirmed defects are that already authorized admin content can render
with public chrome because the shell uses a separate client session as its
authority, and that the proxy redirects an unauthenticated immutable-host
request to the stable host because Auth.js rewrites its request origin.
There is no evidence of a broken Auth.js secret or failing session endpoint in
the available logs. A client session payload issue remains possible and cannot
be ruled out without an authenticated browser review; no persistent Auth.js
configuration was changed on this evidence.

## Fix and scope

The protected layout now provides a constant, non-sensitive admin-surface
context only after `requireAdminSession()` succeeds. `AppShell` and `TopBar`
read this server-issued presentation state. Client session loading, null, or
unavailable no longer removes the rail or replaces the admin top bar with
public navigation or Sign in. The context exposes only `authorized: true` and
`Administrator`; it carries no email, credential, token, or cookie.

The login page remains outside the provider. Rejected server authorization
still redirects signed-out and expired administrators or conceals collectors
before the provider is rendered. Existing per-page `AppHeader` ownership is
preserved, so the protected layout does not introduce a second header or rail.
The proposal-detail implementation and its printing layout are unchanged.

The proxy now rebases only its signed-out login redirects to the origin of the
actual incoming request, preserving the exact callback path. Auth.js still
evaluates the same session, and no persistent `AUTH_URL` or protection setting
changes are needed.

The next immutable staged deployment and desktop/mobile manual review remain
required before any success classification or merge.
