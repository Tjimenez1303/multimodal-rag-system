import { setNonce } from "get-nonce";

// The value index.html holds when no server replaced it, as in development.
const PLACEHOLDER = "__CSP_NONCE__";

/**
 * Hand the page's style nonce to the libraries that inject `<style>` elements, so the
 * Content-Security-Policy accepts them (research section 14). Radix's scroll lock
 * reads it through `get-nonce`.
 *
 * @param document - The page. Vite's `html.cspNonce` writes a `csp-nonce` meta tag,
 *   whose placeholder nginx replaces per request.
 * @returns The nonce applied, or `null` when the page carries none.
 */
export function applyStyleNonce(document: Document): string | null {
  const meta = document.querySelector<HTMLMetaElement>('meta[property="csp-nonce"]');
  // Browsers hide the attribute once the policy applies, and keep the property.
  const nonce = meta?.nonce || meta?.getAttribute("nonce");
  if (!nonce || nonce === PLACEHOLDER) return null;
  setNonce(nonce);
  return nonce;
}
