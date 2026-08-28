import { FileText, GitBranch, ScrollText, Send, Share2, Target, type LucideIcon } from "lucide-react";

export interface CaseTab {
  to: string;
  label: string;
  icon: LucideIcon;
  end?: boolean;
}

/** The six case-scoped investigation pages, shared between the case
 * workspace's own tab bar and the global nav's "Case Workspace" section
 * (which links into whichever case was most recently opened). */
export const CASE_TABS: CaseTab[] = [
  { to: "", label: "Overview", icon: FileText, end: true },
  { to: "network", label: "Network", icon: Share2 },
  { to: "rings", label: "Rings & Corridors", icon: GitBranch },
  { to: "prediction", label: "Prediction", icon: Target },
  { to: "intervention", label: "Intervention", icon: Send },
  { to: "audit", label: "Action & Audit", icon: ScrollText },
];
