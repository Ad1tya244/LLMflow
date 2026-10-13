import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { ConnectionProvider } from "./lib/store";
import "./styles.css";

const el = document.getElementById("root");
if (!el) throw new Error("root element missing");
createRoot(el).render(
  <StrictMode>
    <ConnectionProvider>
      <App />
    </ConnectionProvider>
  </StrictMode>,
);
