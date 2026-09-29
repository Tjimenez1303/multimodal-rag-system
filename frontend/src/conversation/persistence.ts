import { emptyConversation, type Conversation } from "@/conversation/state";

/** `sessionStorage` key of the conversation (data-model section 1.1). */
export const CONVERSATION_KEY = "multimodal-rag.conversation.v1";

/**
 * Read the conversation of this tab. Turns stored as waiting come back stopped by the
 * reload, and held turns keep their order (data-model section 1.1).
 *
 * @returns The stored conversation, or an empty one when nothing valid is stored.
 */
export function loadConversation(): Conversation {
  const stored = sessionStorage.getItem(CONVERSATION_KEY);
  if (stored === null) return emptyConversation;
  try {
    const parsed = JSON.parse(stored) as Partial<Conversation>;
    if (parsed.version !== 1 || !Array.isArray(parsed.turns)) return emptyConversation;
    // A waiting turn lost its request with the old page, so it can only be retried.
    const turns = parsed.turns.map((turn) =>
      turn.state === "waiting"
        ? { ...turn, state: "stopped" as const, stopReason: "reload" as const }
        : turn,
    );
    return { version: 1, turns };
  } catch {
    // A damaged value starts the tab empty rather than failing the page.
    return emptyConversation;
  }
}

/**
 * Write the conversation of this tab, so it survives a reload (FR-003).
 *
 * @param conversation - The conversation to keep.
 * @returns Whether it was saved, or refused because the storage is full.
 */
export function saveConversation(
  conversation: Conversation,
): "saved" | "quota_exceeded" {
  try {
    sessionStorage.setItem(CONVERSATION_KEY, JSON.stringify(conversation));
    return "saved";
  } catch (error) {
    if (error instanceof DOMException && error.name === "QuotaExceededError") {
      return "quota_exceeded";
    }
    throw error;
  }
}
