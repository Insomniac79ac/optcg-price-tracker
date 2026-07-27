import { AppHeader } from "@/components/AppHeader";
import { PageHeader } from "@/components/ui/PageHeader";
import { requireAdminSession } from "@/lib/adminSession";

/** The default post-login admin destination (see /admin/login's
 * DEFAULT_ADMIN_DESTINATION) and SidebarNav's single "Admin" entry target -
 * the detailed operational route list lives in AdminSubNav, rendered by the
 * parent layout on every /admin/* page including this one. */
export default async function AdminIndexPage() {
  const identity = await requireAdminSession();

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-3xl px-4 py-10">
        <PageHeader
          title="Admin"
          description={`Signed in as ${identity.email}. Pick a section above.`}
        />
        <div className="panel p-6 text-sm text-text-secondary">
          <p>
            This is a temporary staging-only administrator login - see{" "}
            <code className="mono text-text-primary">docs/staging_deployment.md</code> for the
            architecture, session policy, and planned migration to Google OAuth plus an
            admin-email allowlist.
          </p>
        </div>
      </main>
    </div>
  );
}
