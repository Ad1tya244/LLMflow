import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { initAnalytics } from "./lib/analytics";
import { ConnectionProvider } from "./lib/store";
import "./styles.css";

initAnalytics();

const el = document.getElementById("root");
if (!el) throw new Error("root element missing");
createRoot(el).render(
  <StrictMode>
    <ConnectionProvider>
      <App />
    </ConnectionProvider>
  </StrictMode>,
);
