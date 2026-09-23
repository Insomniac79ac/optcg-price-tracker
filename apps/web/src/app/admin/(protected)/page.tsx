import Link from "next/link";
import { AdminPageHeader, AdminPageShell, AdminSection, AdminStatusBadge } from "@/components/admin/AdminPage";
import { ADMIN_NAVIGATION } from "@/components/admin/adminNavigation";
import styles from "@/components/admin/AdminShell.module.css";
import { requireAdminSession } from "@/lib/adminSession";

export default async function AdminIndexPage() {
  await requireAdminSession();
  return <AdminPageShell>
    <AdminPageHeader title="Admin overview" description="Catalogue, source evidence and operations in one workspace." actions={<AdminStatusBadge>Administrator</AdminStatusBadge>} />
    <div className={styles.launchpad}>
      {ADMIN_NAVIGATION.map((group) => <AdminSection key={group.label} title={group.label}>
        <p>{group.description}</p>
        <div className={styles.destinations}>
          {group.routes.filter(([href]) => href !== "/admin").map(([href, label]) => <Link key={href} href={href} prefetch={false}>{label}<span aria-hidden="true">→</span></Link>)}
        </div>
      </AdminSection>)}
    </div>
  </AdminPageShell>;
}
