# Admin Atlas UX 1A

## Design audit

The reference is the public Home, Cards and Market shell, including
`PublicShell.module.css`, `TopBar` and the existing uncropped card artwork.

| Area | Previous admin interface | Atlas admin implementation |
| --- | --- | --- |
| Brand | Large raster lockup on desktop, square mark on mobile | Same compact compass and wordmark as public Atlas |
| Foundation | Warm charcoal root palette | Public Atlas blue-black surfaces and readable cool text |
| Navigation | Collector sidebar plus 25 wrapped horizontal links | Four collapsible operational groups, teal active edge |
| Width | Mixed page widths; printing cards split into half rows | Shared full-width operational page; one detailed printing per row |
| Typography | Small generic headings and uniformly dense metadata | Compact sans-serif headings; codes and technical identifiers use mono |
| Surfaces | Flat panels with little content hierarchy | Section panels, separated filters, primary identity and expandable technical metadata |
| Controls | Inconsistent dense spacing | Existing behavior with consistent filter panels, teal focus and clear status |
| Mobile | Collector drawer; legacy horizontal links still visible | Grouped native modal drawer; no public bottom navigation |

The public shell's CSS and destinations are unchanged. Legacy admin page bodies
inherit the new shell palette and grouped navigation. Overview and Proposal
Review queue/detail adopt the shared admin page primitives. The overview only
renders static destinations; it performs no operational data fetch. The queue
keeps its readable card layout through tablet widths and switches to a table at
1280px. The grouped rail also begins at 1280px, leaving landscape tablets
with the drawer and full-width content. Admin account text and the workspace label also wait for desktop space.

## Session contract

The administrator authorization lifetime remains four hours. Initial credentials
sign-in records `sessionKind: admin`. At the cutoff, the JWT loses its active
role and retains only the safe kind/expired flag needed for reauthentication.
The browser never receives the role-expiry timestamp or credentials. Expired
admin sessions do not receive a collector API bearer token.

Proxy redirects expired administrators with the original path and query plus
`reason=session-expired`. It overwrites a navigation-only request header for the
independent server layout boundary; that header never grants access and its
callback is validated again. Collector sessions remain concealed by not-found.
API handlers retain JSON authorization failures with no HTML redirect or upstream
call for unauthorized sessions. The login form returns to the validated callback.

Existing active JWTs gain the kind marker on their next evaluation. Historical
tokens already demoted before this change contain no reliable admin-kind marker;
they are not promoted or classified from an email or subject guess. A normal
fresh admin sign-in establishes the explicit contract.

## Proposal layout and safety

Detailed printing cards use one full-width row each. A container query chooses
artwork beside content only when the actual card width supports it; otherwise
they stack. Artwork is centred, bounded to 20rem and uses `object-contain`.
Metadata has one or two columns, never three. Ordinary values use word wrapping;
only dedicated technical identifiers use aggressive wrapping. Technical print
metadata remains available in a closed details section. All three evidence
sections have explicit empty states.

Proposal fetch/filter logic, decisions, actor assertions, idempotency, reviewer
masking and terminal-state rendering are unchanged. No backend, migration,
database or collector code is changed. Browser validation uses intercepted
artwork to prevent source-site access, including indirect image-proxy fetching.

## Validation

Validation results and exact preview/deployment review are recorded in the task
report. Local checks use Vitest, TypeScript and ESLint. Production builds belong
to CI and Vercel. No dependency installation, Docker build, migration or live
proposal mutation is part of this tranche.

### Local and staging baseline evidence (2026-09-23)

- Base: `268edfc1822bdf1537e765125d7c5ac9284f684a`, current `origin/staging`.
- Targeted Vitest: 17 files, 270 tests passed. After the tablet queue and header
  adjustments, both affected suites passed again (15 tests).
- TypeScript `tsc --noEmit`, ESLint over all touched TypeScript files, and
  `git diff --check`: passed.
- A staging-only connection, with `default_transaction_read_only=on`, passed all
  repository database fingerprints at revision `b8e04219d6c3`.
- Counts: 4,027 groups; 6,149 alternatives; pending/approved/rejected 4,024/3/0;
  839 mappings; zero superseded; two duplicate-current canonical identity groups.
- Approved mapping links: 1128 → 1159, 1129 → 1158, 3815 → 1160.
- Visual-review targets: ambiguous 1501 and unresolved identity 1710, alongside
  the three approved groups, overview and queue.

CI, exact Vercel preview review and deployment remain separate release gates.
No merge is permitted before the exact reviewed head passes those gates.

- Browser validation with the mock-only API: overview, queue and detail reviewed at
  1512, 1024, 820 and 390 pixels. No horizontal page overflow; rail only on desktop;
  native drawer and Escape behavior verified on tablets/mobile. Printing artwork
  uses `object-fit: contain`, primary metadata has two columns on desktop/tablet
  and one on mobile, and technical metadata is closed initially. Local artwork
  fixtures replaced image requests, so no source sites were contacted.
- The final landscape-tablet correction passed all three affected suites (26 tests)
  and touched-file ESLint. These local checks do not replace exact-preview review.
