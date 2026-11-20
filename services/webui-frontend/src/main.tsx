import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
// plotly.js's own rules as a stylesheet, which the build serves from this
// origin. The marker in index.html stops plotly.js from inserting the same
// rules as an inline <style>, which the Content-Security-Policy refuses.
import "plotly.js/dist/plotly.css";
import App from "./App";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>
);
