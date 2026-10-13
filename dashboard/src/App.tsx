import { ErrorBoundary } from "./components/ErrorBoundary";
import { Shell } from "./components/Shell";
import { Skeleton } from "./components/ui";
import { useRoute } from "./lib/route";
import { useConnection } from "./lib/store";
import { ApiKeys } from "./pages/ApiKeys";
import { AuthScreen } from "./pages/AuthScreen";
import { Benchmarks } from "./pages/Benchmarks";
import { Connect } from "./pages/Connect";
import { Overview } from "./pages/Overview";
import { Playground } from "./pages/Playground";
import { Providers } from "./pages/Providers";
import { Requests } from "./pages/Requests";
import { Settings } from "./pages/Settings";

export function App() {
  const route = useRoute();
  const { auth } = useConnection();

  if (auth === "checking") {
    return (
      <div className="auth-wrap" aria-busy>
        <div className="auth-card stack">
          <Skeleton height={28} width={140} />
          <Skeleton height={120} />
        </div>
      </div>
    );
  }
  if (auth === "signed_out") return <AuthScreen />;

  return (
    <Shell route={route}>
      <ErrorBoundary resetKey={route}>
        {route === "overview" && <Overview />}
        {route === "requests" && <Requests />}
        {route === "providers" && <Providers />}
        {route === "keys" && <ApiKeys />}
        {route === "connect" && <Connect />}
        {route === "playground" && <Playground />}
        {route === "benchmarks" && <Benchmarks />}
        {route === "settings" && <Settings />}
      </ErrorBoundary>
    </Shell>
  );
}
