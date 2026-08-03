
import { Component, type ErrorInfo, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import "./styles/index.css";

type AppErrorBoundaryState = { error: Error | null };

class AppErrorBoundary extends Component<{ children: ReactNode }, AppErrorBoundaryState> {
  state: AppErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): AppErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Flux FleetOps failed to render.", error, info);
  }

  render() {
    if (!this.state.error) return this.props.children;

    return <StartupFailure error={this.state.error} />;
  }
}

function StartupFailure({ error }: { error?: unknown }) {
  const detail = import.meta.env.DEV && error instanceof Error ? error.message : null;
  const errorStatus =
    error && typeof error === "object" && "status" in error
      ? Number((error as { status?: unknown }).status)
      : null;
  const errorMessage =
    error instanceof Error ? error.message.toLowerCase() : "";
  const isSessionError =
    errorStatus === 401 ||
    errorMessage.includes("session has expired") ||
    errorMessage.includes("authentication required") ||
    errorMessage.includes("unauthorized") ||
    errorMessage.includes("invalid token");
  const retry = () => {
    if (isSessionError) {
      localStorage.removeItem("flux_token");
      localStorage.removeItem("flux_user");
    }
    window.location.reload();
  };

  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-50 p-6 text-slate-900">
      <section className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-8 text-center shadow-sm">
        <div className="mx-auto mb-5 flex h-12 w-12 items-center justify-center rounded-xl bg-blue-600 text-xl font-bold text-white">
          F
        </div>
        <h1 className="text-xl font-semibold">Flux FleetOps could not start</h1>
        <p className="mt-2 text-sm leading-6 text-slate-600">
          {isSessionError
            ? "Reset the expired session and sign in again."
            : "Reload the application to try again. Your current session will be preserved."}
        </p>
        {detail ? (
          <p className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-left text-xs text-red-700">{detail}</p>
        ) : null}
        <button
          type="button"
          onClick={retry}
          className="mt-6 w-full rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-blue-700"
        >
          {isSessionError ? "Reset session and retry" : "Reload application"}
        </button>
      </section>
    </main>
  );
}

const container = document.getElementById("root");
if (!container) throw new Error("Application root element is missing.");
const root: Root = createRoot(container);

void import("./app/App.tsx")
  .then(({ default: App }) => {
    root.render(
      <AppErrorBoundary>
        <App />
      </AppErrorBoundary>,
    );
  })
  .catch((error) => {
    console.error("Flux FleetOps failed during startup.", error);
    root.render(<StartupFailure error={error} />);
  });
