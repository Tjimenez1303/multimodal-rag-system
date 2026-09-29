import { useEffect, useReducer, useState, type Dispatch } from "react";

import { loadConversation, saveConversation } from "@/conversation/persistence";
import {
  conversationReducer,
  type Conversation,
  type ConversationAction,
} from "@/conversation/state";

/** The conversation of this tab and whether it will survive a reload. */
export interface ConversationStore {
  conversation: Conversation;
  dispatch: Dispatch<ConversationAction>;
  /** `false` once the browser refused to store the conversation (storage full). */
  persisted: boolean;
}

/**
 * Keep the conversation in memory and in the tab's `sessionStorage` (FR-003).
 *
 * @returns The conversation, its dispatcher and its persistence status.
 */
export function useConversation(): ConversationStore {
  const [conversation, dispatch] = useReducer(
    conversationReducer,
    undefined,
    loadConversation,
  );
  const [persisted, setPersisted] = useState(true);
  useEffect(() => {
    // The effect writes to sessionStorage, an external system, and keeps its outcome.
    // oxlint-disable-next-line react/set-state-in-effect
    setPersisted(saveConversation(conversation) === "saved");
  }, [conversation]);
  return { conversation, dispatch, persisted };
}
