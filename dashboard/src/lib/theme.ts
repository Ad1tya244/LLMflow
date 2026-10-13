export type ThemeChoice = "light" | "dark";

export function currentTheme(): ThemeChoice {
  const explicit = document.documentElement.dataset.theme;
  if (explicit === "light" || explicit === "dark") return explicit;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function setTheme(theme: ThemeChoice): void {
  document.documentElement.dataset.theme = theme;
  try {
    localStorage.setItem("llmflow.theme", theme);
  } catch {
    /* preference not persisted */
  }
}
