"use client";

import { Component, type ErrorInfo, type ReactNode } from "react";

type Props = { children: ReactNode };
type State = { failed: boolean };

export class ErrorBoundary extends Component<Props, State> {
  state: State = { failed: false };

  static getDerivedStateFromError(): State {
    return { failed: true };
  }

  componentDidCatch(_: Error, __: ErrorInfo) {
    // Do not include message content or credentials in client-side diagnostics.
  }

  render() {
    if (this.state.failed) {
      return <main className="app-error-state"><h1>界面出现问题</h1><p>请刷新应用后重试；已保存的本地项目不会丢失。</p></main>;
    }
    return this.props.children;
  }
}
