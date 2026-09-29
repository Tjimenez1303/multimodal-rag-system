import { BookOpenTextIcon, SquarePenIcon } from "lucide-react";
import { useMemo } from "react";
import type { GetTargetScrollTop } from "use-stick-to-bottom";

import {
  Conversation,
  ConversationContent,
  ConversationEmptyState,
  ConversationScrollButton,
} from "@/components/ai-elements/conversation";
import {
  PromptInputProvider,
  usePromptInputController,
} from "@/components/ai-elements/prompt-input";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { QuestionInput } from "@/conversation/QuestionInput";
import { TurnActionsContext, type TurnActions } from "@/conversation/turnActions";
import { TurnView } from "@/conversation/TurnView";
import { useConversation } from "@/conversation/useConversation";
import { useQuestionQueue } from "@/conversation/useQuestionQueue";

// Space kept above a new turn when it is scrolled to the top of the view.
const TURN_TOP_MARGIN = 24;

// "Bottom" is the top of the newest turn when that turn is taller than the view, so a
// long answer arrives with its question and first lines in view.
const newestTurnTop: GetTargetScrollTop = (bottom, { contentElement }) => {
  const newest = contentElement.lastElementChild;
  if (!(newest instanceof HTMLElement)) return bottom;
  return Math.max(0, Math.min(bottom, newest.offsetTop - TURN_TOP_MARGIN));
};

/** Props of {@link ConversationView}. */
export interface ConversationViewProps {
  /** Opens the upload control, offered when no document is ready. */
  onRequestUpload?: (() => void) | undefined;
}

/**
 * The conversation: turns in order, the question input, and "New conversation"
 * (FR-001 to FR-007).
 */
export function ConversationView(props: ConversationViewProps) {
  return (
    <PromptInputProvider>
      <ConversationBody {...props} />
    </PromptInputProvider>
  );
}

function ConversationBody({ onRequestUpload }: ConversationViewProps) {
  const { conversation, dispatch, persisted } = useConversation();
  const { textInput } = usePromptInputController();
  const { setInput } = textInput;
  const { submit, stop, retry, busy } = useQuestionQueue(conversation, dispatch, {
    onReturnQuestion: setInput,
  });
  const actions = useMemo<TurnActions>(
    () => ({
      retry,
      edit: setInput,
      askAcrossAll: (question) => submit(question, []),
      requestUpload: onRequestUpload,
    }),
    [retry, setInput, submit, onRequestUpload],
  );
  const { turns } = conversation;
  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex h-12 shrink-0 items-center justify-between border-b px-6">
        <h1 className="text-sm font-semibold">Manual Assistant</h1>
        <NewConversationButton
          disabled={turns.length === 0}
          onConfirm={() => {
            stop();
            dispatch({ type: "cleared" });
          }}
        />
      </header>
      {!persisted && (
        <output className="block border-b bg-amber-50 px-6 py-2 text-xs text-amber-950">
          This conversation won&apos;t survive a reload: the browser&apos;s storage for
          this tab is full.
        </output>
      )}
      <TurnActionsContext value={actions}>
        <Conversation className="min-h-0 flex-1" targetScrollTop={newestTurnTop}>
          <ConversationContent className="mx-auto w-full max-w-6xl gap-10 px-6 py-6">
            {turns.length === 0 ? (
              <ConversationEmptyState
                className="py-24"
                icon={<BookOpenTextIcon aria-hidden="true" className="size-6" />}
                title="Ask about your manuals"
                description="Answers cite the document and page they come from, with the figure they rely on."
              />
            ) : (
              turns.map((turn) => <TurnView key={turn.id} turn={turn} />)
            )}
          </ConversationContent>
          <ConversationScrollButton aria-label="Scroll to the latest turn" />
        </Conversation>
      </TurnActionsContext>
      <div className="shrink-0 border-t bg-muted/30 px-6 py-3">
        <div className="mx-auto max-w-6xl">
          <QuestionInput
            onSubmit={(question) => submit(question)}
            busy={busy}
            onStop={stop}
          />
        </div>
      </div>
    </div>
  );
}

function NewConversationButton({
  disabled,
  onConfirm,
}: {
  disabled: boolean;
  onConfirm: () => void;
}) {
  return (
    <AlertDialog>
      <AlertDialogTrigger asChild>
        <Button variant="outline" size="sm" disabled={disabled}>
          <SquarePenIcon aria-hidden="true" />
          New conversation
        </Button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Start a new conversation?</AlertDialogTitle>
          <AlertDialogDescription>
            Every question and answer in this tab is cleared. This cannot be undone.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction onClick={onConfirm}>Clear conversation</AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
