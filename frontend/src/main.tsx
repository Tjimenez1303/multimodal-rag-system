import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "@/App";
import { loadConfig } from "@/config";
import { applyStyleNonce } from "@/csp";
import { ConnectionNotice } from "@/failures/ConnectionNotice";

import "./index.css";

const MAX_BACKOFF_SECONDS = 10;
applyStyleNonce(document);
const root = createRoot(document.getElementById("root")!);

// The client never starts with guessed values: it waits for a valid /config.json,
// retrying after 1, 2, 4 and then at most 10 seconds (research section 11).
async function start(attempt = 0): Promise<void> {
  try {
    const config = await loadConfig();
    root.render(
      <StrictMode>
        <App config={config} />
      </StrictMode>,
    );
  } catch {
    root.render(
      <StrictMode>
        <div className="p-4">
          <ConnectionNotice forceVisible />
        </div>
      </StrictMode>,
    );
    const delaySeconds = Math.min(2 ** attempt, MAX_BACKOFF_SECONDS);
    setTimeout(() => void start(attempt + 1), delaySeconds * 1000);
  }
}

void start();
