import type { ReactNode } from "react";
import ExportToolbar, { type ExportToolbarProps } from "./ExportToolbar";

export interface PageHeaderProps {
  title: string;
  subtitle?: ReactNode;
  exports?: ExportToolbarProps;
}

export default function PageHeader({ title, subtitle, exports }: PageHeaderProps) {
  return (
    <header style={{
      display: "flex", justifyContent: "space-between",
      alignItems: "flex-start", gap: 16, marginBottom: 12,
    }}>
      <div style={{ minWidth: 0 }}>
        <h2 style={{ margin: 0 }}>{title}</h2>
        {subtitle && (
          <p style={{ color: "#9aa9d8", margin: "4px 0 0 0", maxWidth: 820 }}>
            {subtitle}
          </p>
        )}
      </div>
      {exports && (
        <div style={{ flexShrink: 0 }}>
          <ExportToolbar {...exports} />
        </div>
      )}
    </header>
  );
}
