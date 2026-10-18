import { ErrorBoundary } from "./components/ErrorBoundary";
import { Shell } from "./components/Shell";
import { Skeleton } from "./components/ui";
import { useRoute } from "./lib/route";
import { useConnection } from "./lib/store";
import { ApiKeys } from "./pages/ApiKeys";
import { AuthScreen } from "./pages/AuthScreen";
import { Landing } from "./pages/Landing";
import { useAuthRoute } from "./lib/authRoute";
import { Connect } from "./pages/Connect";
import { Overview } from "./pages/Overview";
import { Playground } from "./pages/Playground";
import { Providers } from "./pages/Providers";
import { Requests } from "./pages/Requests";
import { Settings } from "./pages/Settings";
import { WorkspacePage } from "./pages/Workspace";

export function App() {
  const route = useRoute();
  const { auth } = useConnection();
  const authRoute = useAuthRoute();

  if (auth === "checking") {
    // Never make a visitor wait on the (possibly sleeping) API to see the landing page.
    if (authRoute === "landing") return <Landing />;
    return (
      <div className="auth-wrap" aria-busy>
        <div className="auth-card stack">
          <Skeleton height={28} width={140} />
          <Skeleton height={120} />
        </div>
      </div>
    );
  }
  if (auth === "signed_out") {
    if (authRoute === "landing") return <Landing />;
    return <AuthScreen key={authRoute} initialMode={authRoute} />;
  }

  return (
    <Shell route={route}>
      <ErrorBoundary resetKey={route}>
        {route === "overview" && <Overview />}
        {route === "requests" && <Requests />}
        {route === "providers" && <Providers />}
        {route === "keys" && <ApiKeys />}
        {route === "connect" && <Connect />}
        {route === "playground" && <Playground />}
        {route === "workspace" && <WorkspacePage />}
        {route === "settings" && <Settings />}
      </ErrorBoundary>
    </Shell>
  );
}
