import { getNonce } from "get-nonce";

import { applyStyleNonce } from "@/csp";

function page(content: string | null): Document {
  const document = window.document.implementation.createHTMLDocument("page");
  if (content !== null) {
    const meta = document.createElement("meta");
    meta.setAttribute("property", "csp-nonce");
    meta.setAttribute("nonce", content);
    document.head.append(meta);
  }
  return document;
}

test("the nonce nginx wrote into the page is handed to injected styles", () => {
  expect(applyStyleNonce(page("4f1c0a9e2b7d4c55a1e0f3b6c8d2e7a1"))).toBe(
    "4f1c0a9e2b7d4c55a1e0f3b6c8d2e7a1",
  );
  expect(getNonce()).toBe("4f1c0a9e2b7d4c55a1e0f3b6c8d2e7a1");
});

test("a page that no server filled carries no nonce", () => {
  expect(applyStyleNonce(page("__CSP_NONCE__"))).toBeNull();
  expect(applyStyleNonce(page(null))).toBeNull();
});
