// AppHeader is kept as a re-export so every existing page (~30 files import
// `{ AppHeader } from "@/components/AppHeader"` and render `<AppHeader />`
// as the first thing in their root div) picks up the new sidebar+topbar
// shell with zero per-page edits. New code should import AppShell directly
// from "@/components/ui/AppShell" - this file is a compatibility shim, not
// where the implementation lives.
export { AppShell as AppHeader } from "@/components/ui/AppShell";
