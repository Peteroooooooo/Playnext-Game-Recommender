import { Component, StrictMode, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles.css";

/** A render error shows a way back instead of an empty page. */
class Guard extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(e: unknown) {
    console.error(e);
  }

  render() {
    if (!this.state.failed) return this.props.children;
    const zh = document.documentElement.lang !== "en";
    return (
      <div className="crash" role="alert">
        <p>{zh ? "页面出错了。" : "Something went wrong on this page."}</p>
        <button type="button" className="btn" onClick={() => window.location.reload()}>
          {zh ? "重新加载" : "Reload"}
        </button>
      </div>
    );
  }
}

const root = document.getElementById("root");
if (!root) throw new Error("#root not found");

createRoot(root).render(
  <StrictMode>
    <Guard>
      <App />
    </Guard>
  </StrictMode>,
);
