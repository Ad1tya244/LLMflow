import { Component, type ErrorInfo, type ReactNode } from "react";
import { ErrorBanner } from "./ui";

interface State {
  error: Error | null;
}

/** Keeps one broken page from blanking the whole app. */
export class ErrorBoundary extends Component<{ children: ReactNode; resetKey: string }, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("render error", error, info.componentStack);
  }

  componentDidUpdate(prev: { resetKey: string }): void {
    if (prev.resetKey !== this.props.resetKey && this.state.error) this.setState({ error: null });
  }

  render() {
    if (this.state.error) {
      return (
        <div className="page">
          <ErrorBanner message="This page hit an unexpected error. Reload to try again." />
        </div>
      );
    }
    return this.props.children;
  }
}
