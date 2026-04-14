"use client";

import { Component, type ReactNode } from "react";

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
  name?: string;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback;
      return (
        <div className="bg-red-500/5 border border-red-500/20 rounded-xl p-4">
          <div className="flex items-center gap-2 mb-2">
            <span className="text-red-400 text-sm font-semibold">
              ⚠️ {this.props.name || "Component"} Error
            </span>
          </div>
          <p className="text-xs text-red-300/70">
            {this.state.error?.message || "An unexpected error occurred."}
          </p>
          <button
            onClick={() => this.setState({ hasError: false, error: null })}
            className="mt-2 text-[10px] text-red-400 hover:text-red-300 underline"
          >
            Try again
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
