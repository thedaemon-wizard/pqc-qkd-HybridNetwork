import type { ReactNode } from "react";

/** No `exports` slot. This component used to accept an ExportToolbarProps and
 *  render the toolbar in a top-right flex slot; no page ever passed it, because
 *  the layout it encoded was reversed early on -- every one of the nine toolbar
 *  pages renders ExportToolbar BELOW the description instead, so the buttons do
 *  not collide with the subtitle. The prop, the import and the branch were dead
 *  code that documented a layout the project had decided against. */
export interface PageHeaderProps {
  title: string;
  subtitle?: ReactNode;
}

export default function PageHeader({ title, subtitle }: PageHeaderProps) {
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
    </header>
  );
}
