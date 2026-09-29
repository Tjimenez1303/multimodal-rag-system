import {
  PromptInput,
  PromptInputBody,
  PromptInputFooter,
  PromptInputSubmit,
  PromptInputTextarea,
  PromptInputTools,
  usePromptInputController,
} from "@/components/ai-elements/prompt-input";

/** Props of {@link QuestionInput}. */
export interface QuestionInputProps {
  onSubmit: (question: string) => void;
  /** Whether a question is being answered. The send button then stops it. */
  busy: boolean;
  onStop: () => void;
}

/**
 * The question box: several lines, Enter to send, Shift+Enter for a new line, and no
 * sending of a blank question (FR-001). While a question is answered, the send button
 * becomes a stop button, and questions sent meanwhile are held (FR-006).
 *
 * It must be rendered inside AI Elements' `PromptInputProvider`, which holds the text.
 */
export function QuestionInput({ onSubmit, busy, onStop }: QuestionInputProps) {
  const { textInput } = usePromptInputController();
  const blank = textInput.value.trim() === "";
  return (
    <PromptInput
      className="rounded-xl bg-background shadow-xs"
      onSubmit={({ text }) => {
        if (text.trim() !== "") onSubmit(text);
      }}
    >
      <PromptInputBody>
        <PromptInputTextarea
          aria-label="Ask a question about your manuals"
          placeholder="Ask a question about your manuals…"
          className="min-h-12 text-[0.9375rem]"
        />
      </PromptInputBody>
      <PromptInputFooter>
        <PromptInputTools>
          <span className="px-1 text-xs text-muted-foreground">
            {busy
              ? "Questions sent now wait until the current answer arrives"
              : "Enter to send, Shift+Enter for a new line"}
          </span>
        </PromptInputTools>
        <PromptInputSubmit
          aria-label={busy ? "Stop" : "Send question"}
          status={busy ? "streaming" : "ready"}
          onStop={onStop}
          disabled={!busy && blank}
        />
      </PromptInputFooter>
    </PromptInput>
  );
}
