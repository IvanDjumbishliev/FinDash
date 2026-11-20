import { createContext, useContext } from "react";

const THEME_KEY = "findash-theme";

export const ThemeContext = createContext(null);

export function getInitialTheme() {
  const saved = localStorage.getItem(THEME_KEY);
  if (saved === "light" || saved === "dark") return saved;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
}

export function saveTheme(theme) {
  localStorage.setItem(THEME_KEY, theme);
}

export function useTheme() {
  return useContext(ThemeContext);
}
