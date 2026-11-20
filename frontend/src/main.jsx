import ReactDOM from "react-dom/client";
import { Toaster } from "react-hot-toast";
import App from "./App";
import ThemeProvider from "./components/ThemeProvider";
import { applyTheme, getInitialTheme } from "./theme";
import "./styles/base/variables.css";
import "./styles/base/reset.css";
import "./styles/base/app.css";

const initialTheme = getInitialTheme();
applyTheme(initialTheme);

ReactDOM.createRoot(document.getElementById("root")).render(
  <ThemeProvider initialTheme={initialTheme}>
    <App />
    <Toaster toastOptions={{ style: { background: "var(--surface)", color: "var(--ink)" } }} />
  </ThemeProvider>
);
