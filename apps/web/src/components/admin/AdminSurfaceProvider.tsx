"use client";

import { createContext, useContext, type ReactNode } from "react";

type AdminSurface = Readonly<{
  authorized: true;
  displayName: "Administrator";
}>;

const AdminSurfaceContext = createContext<AdminSurface | null>(null);
const AUTHORIZED_ADMIN_SURFACE: AdminSurface = {
  authorized: true,
  displayName: "Administrator",
};

// Only the server-authorized protected layout renders this provider. The
// context carries presentation state, never a session, email, or credential.
export function AdminSurfaceProvider({ children }: { children: ReactNode }) {
  return <AdminSurfaceContext.Provider value={AUTHORIZED_ADMIN_SURFACE}>{children}</AdminSurfaceContext.Provider>;
}

export function useAdminSurface(): AdminSurface | null {
  return useContext(AdminSurfaceContext);
}
