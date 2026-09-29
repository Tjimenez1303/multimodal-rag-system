import { createContext, useContext } from "react";

/** What a turn can ask the conversation to do. */
export interface TurnActions {
  retry: (turnId: string) => void;
  /** Put a question back into the input to be edited and sent again. */
  edit: (question: string) => void;
  /** Ask the same question again with no document restriction. */
  askAcrossAll: (question: string) => void;
  /** Open the upload control, when no document is ready. */
  requestUpload?: (() => void) | undefined;
}

/** Provides the conversation's actions to its turns without re-rendering them. */
export const TurnActionsContext = createContext<TurnActions | null>(null);

/**
 * Read the conversation's actions.
 *
 * @returns The actions, or `null` outside a conversation.
 */
export function useTurnActions(): TurnActions | null {
  return useContext(TurnActionsContext);
}
