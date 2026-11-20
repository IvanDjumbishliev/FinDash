import { useState } from "react";
import PropTypes from "prop-types";
import { applyTheme, saveTheme, ThemeContext } from "../theme";

export default function ThemeProvider({ children, initialTheme }) {
  const [theme, setTheme] = useState(initialTheme);

  function toggleTheme() {
    const next = theme === "light" ? "dark" : "light";
    applyTheme(next);
    saveTheme(next);
    setTheme(next);
  }

  return (
    <ThemeContext.Provider value={{ theme, toggleTheme }}>
      {children}
    </ThemeContext.Provider>
  );
}


ThemeProvider.propTypes = {
  children: PropTypes.node.isRequired,
  initialTheme: PropTypes.oneOf(["light", "dark"]).isRequired,
};
