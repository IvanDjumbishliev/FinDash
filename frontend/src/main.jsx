import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { Toaster } from "react-hot-toast";
import "./styles/base/variables.css";
import "./styles/base/reset.css";
import "./styles/base/app.css";

ReactDOM.createRoot(document.getElementById("root")).render(
  <>
    <App />
    <Toaster />
  </>
);
