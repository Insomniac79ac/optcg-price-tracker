import type { Metadata } from "next";

import { AdminOnlyPageLayout } from "@/components/admin/AdminOnlyPageLayout";

export const metadata: Metadata = { robots: { index: false, follow: false } };

export default AdminOnlyPageLayout;
