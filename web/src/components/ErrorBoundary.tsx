import { Component, type ReactNode } from 'react'

interface Props {
  /** What failed, for the message: "The map", "This view". */
  label: string
  hint?: ReactNode
  children: ReactNode
}

/** Shows a failure in place instead of letting one broken part blank the whole app. */
export class ErrorBoundary extends Component<Props, { error: Error | null }> {
  state = { error: null as Error | null }

  static getDerivedStateFromError(error: Error) {
    return { error }
  }

  componentDidCatch(error: Error) {
    console.error(`${this.props.label} failed:`, error)
  }

  render() {
    const { error } = this.state
    if (!error) return this.props.children
    return (
      <div className="failure" role="alert">
        <strong>{this.props.label} could not load.</strong>
        <code>{error.message}</code>
        {this.props.hint}
      </div>
    )
  }
}

export function WebglHint() {
  return (
    <p className="muted small">
      The map needs WebGL. In Chrome, turn on Settings → System → "Use graphics acceleration when available",
      relaunch, and check that chrome://gpu lists WebGL as hardware accelerated.
    </p>
  )
}
