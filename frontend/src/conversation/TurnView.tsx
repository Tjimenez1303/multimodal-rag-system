import { CircleStopIcon, ClockIcon, RotateCcwIcon } from "lucide-react";
import { memo } from "react";

import { CitationProvider } from "@/answer/citations";
import { AnswerMarkdown } from "@/answer/markdown/AnswerMarkdown";
import { NoInformationState } from "@/answer/NoInformationState";
import { NotCoveredNote } from "@/answer/NotCoveredNote";
import { SourceList } from "@/answer/SourceList";
import type { AnswerBody } from "@/client";
import { Message, MessageContent } from "@/components/ai-elements/message";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import type { Turn } from "@/conversation/state";
import { useTurnActions } from "@/conversation/turnActions";
import { FailureNotice } from "@/failures/FailureNotice";
import { ImageColumn } from "@/images/ImageColumn";

/**
 * One turn of the conversation: the question and its outcome.
 *
 * @param props - The turn.
 */
export const TurnView = memo(function TurnView({ turn }: { turn: Turn }) {
  return (
    <article aria-label={`Question: ${turn.question}`} className="flex flex-col gap-4">
      {/* The question, then whatever its state produced */}
      <Message from="user">
        <MessageContent className="text-[0.9375rem] leading-6 whitespace-pre-wrap">
          {turn.question}
        </MessageContent>
      </Message>
      <TurnOutcome turn={turn} />
    </article>
  );
});

function TurnOutcome({ turn }: { turn: Turn }) {
  // Pick the view of the turn from its state
  const actions = useTurnActions();
  switch (turn.state) {
    case "held":
      // Queued behind the question being answered
      return (
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <ClockIcon aria-hidden="true" className="size-4" />
          Waiting to be sent
        </p>
      );
    case "waiting":
      // Sent and waiting for the service
      return (
        <div
          role="status"
          className="flex items-center gap-2 text-sm text-muted-foreground"
        >
          <Spinner aria-hidden="true" />
          Preparing the answer…
        </div>
      );
    case "stopped":
      // Stopped by the user or by a reload, with a retry button
      return (
        <div className="flex w-fit flex-wrap items-center gap-3 rounded-lg border bg-muted/40 px-3 py-2 text-sm">
          <CircleStopIcon aria-hidden="true" className="size-4 text-muted-foreground" />
          <span>
            {turn.stopReason === "reload" ? "Interrupted by a page reload" : "Stopped"}
          </span>
          <Button variant="outline" size="sm" onClick={() => actions?.retry(turn.id)}>
            <RotateCcwIcon aria-hidden="true" />
            Retry
          </Button>
        </div>
      );
    case "failed": {
      // A failure offers retry or edit, depending on its cause
      const failure = turn.failure;
      if (failure === null) return null;
      const action =
        failure.action === "retry"
          ? { label: "Retry", onAction: () => actions?.retry(turn.id) }
          : failure.action === "edit"
            ? {
                label: "Edit and ask again",
                onAction: () => actions?.edit(turn.question),
              }
            : undefined;
      return (
        <FailureNotice
          message={failure.message}
          reference={failure.reference}
          action={action}
        />
      );
    }
    case "no_information":
      // The documents did not support an answer
      return turn.response === null ? null : (
        <NoInformationState
          response={turn.response}
          restricted={turn.restriction.length > 0}
          onRequestUpload={actions?.requestUpload}
          onAskAcrossAll={() => actions?.askAcrossAll(turn.question)}
        />
      );
    case "answered":
      // A grounded answer with citations and figures
      return turn.response === null ? null : (
        <AnsweredTurn turnId={turn.id} response={turn.response} />
      );
  }
}

function AnsweredTurn({ turnId, response }: { turnId: string; response: AnswerBody }) {
  // Figures get their own column only when the answer has any
  const withImages =
    response.primary_image !== null || response.related_images.length > 0;
  return (
    // Shares the highlighted citation between the markers and the source lines
    <CitationProvider turnId={turnId} response={response}>
      <Message from="assistant" className="max-w-full">
        <section
          aria-label="Answer"
          data-layout={withImages ? "with-images" : "text-only"}
          className={
            withImages
              ? "grid grid-cols-[minmax(0,1fr)_minmax(16rem,22rem)] gap-8"
              : "grid grid-cols-1"
          }
        >
          <div className="flex min-w-0 flex-col gap-5">
            {/* Answer text with clickable [n] markers */}
            <AnswerMarkdown
              answer={response.answer}
              citationNumbers={response.citations.map((citation) => citation.number)}
            />
            {/* What the documents left unanswered, if anything */}
            {response.not_covered !== null && (
              <NotCoveredNote text={response.not_covered} />
            )}
            {/* One numbered line per citation */}
            {response.citations.length > 0 && (
              <div className="flex flex-col gap-2">
                <h3 className="text-xs font-medium text-muted-foreground">Sources</h3>
                <SourceList response={response} />
              </div>
            )}
          </div>
          {/* Primary figure first, then the related ones */}
          {withImages && (
            <aside aria-label="Figures" className="border-l pl-6">
              <ImageColumn
                primary={response.primary_image}
                related={response.related_images}
              />
            </aside>
          )}
        </section>
      </Message>
    </CitationProvider>
  );
}
