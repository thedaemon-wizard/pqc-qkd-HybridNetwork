import { Component, type ErrorInfo, type ReactNode } from "react";
import { colors } from "../lib/commonStyles";
import { useNarrowLayout } from "../lib/layout";

/**
 * Where the other pages are listed: the sidebar from 768px up, and below it
 * the top bar's Menu button (App.tsx), behind which the sidebar is hidden. A
 * function component because the boundary is a class and cannot call hooks.
 */
function NavigationName() {
  return <>{useNarrowLayout() ? "the Menu button" : "the sidebar"}</>;
}

/**
 * Catches a render error in one page so it does not blank the whole app.
 *
 * There was no boundary anywhere in src, so a page that threw during render --
 * `/verify` calling `.map` on an error body, for instance -- unmounted the
 * entire tree, sidebar included, and left a blank window with nothing to click.
 * App.tsx wraps the routes in this, keyed by the path, so navigating away
 * clears the error.
 */
export default class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state: { error: Error | null } = { error: null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("page render failed", error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <div role="alert" style={{ border: `1px solid ${colors.danger}`, borderRadius: 8,
                                   padding: 16, color: colors.textPri, background: colors.panelBg }}>
          <h2 style={{ marginTop: 0 }}>This page failed to render</h2>
          <p style={{ color: colors.textSec }}>
            {this.state.error.message || String(this.state.error)}
          </p>
          <p style={{ color: colors.textMute, fontSize: 12 }}>
            The other pages are unaffected; choose one from <NavigationName />, or reload this one.
          </p>
        </div>
      );
    }
    return this.props.children;
  }
}
