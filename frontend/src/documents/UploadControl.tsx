import { CheckIcon, UploadIcon, XIcon } from "lucide-react";
import {
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
  type Ref,
} from "react";

import { isPdf, uploadDocument } from "@/api/upload";
import type { DocumentBody } from "@/client";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { useDocumentPanel } from "@/documents/documentPanelContext";
import { FailureNotice } from "@/failures/FailureNotice";
import { NOT_A_PDF, type UploadFailure } from "@/failures/messages";

/** A file sent from this tab (data-model section 1.6). In memory only. */
interface TrackedUpload {
  id: string;
  file: File;
  state: "sending" | "accepted" | "rejected" | "failed";
  sentFraction: number;
  documentId: string | null;
  alreadyIngested: boolean;
  failure: UploadFailure | null;
}

/** What the document list can ask of the upload control. */
export interface UploadControlHandle {
  /** Open the file picker, as "Upload again" does. */
  openFilePicker: () => void;
}

/** Props of {@link UploadControl}. */
export interface UploadControlProps {
  /** The loaded library, to tell when an accepted upload has appeared in it. */
  documents: readonly DocumentBody[];
  /** Read the library again once an upload is accepted. */
  onAccepted: () => void;
  ref?: Ref<UploadControlHandle>;
}

/**
 * Uploads PDFs with transfer progress, and shows each file's rejection, failure or
 * "Already ingested" (FR-032, FR-036, FR-037).
 */
export function UploadControl({ documents, onAccepted, ref }: UploadControlProps) {
  const input = useRef<HTMLInputElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const [uploads, setUploads] = useState<TrackedUpload[]>([]);
  const panel = useDocumentPanel();

  const openFilePicker = useCallback(() => input.current?.click(), []);
  useImperativeHandle(ref, () => ({ openFilePicker }), [openFilePicker]);
  useEffect(() => {
    panel?.registerUploadFocus(() => button.current?.focus());
    return () => panel?.registerUploadFocus(null);
  }, [panel]);

  const update = (id: string, changes: Partial<TrackedUpload>) =>
    setUploads((current) =>
      current.map((upload) => (upload.id === id ? { ...upload, ...changes } : upload)),
    );

  const send = async (file: File, id: string = crypto.randomUUID()) => {
    const tracked: TrackedUpload = {
      id,
      file,
      state: "sending",
      sentFraction: 0,
      documentId: null,
      alreadyIngested: false,
      failure: null,
    };
    setUploads((current) => [...current.filter((upload) => upload.id !== id), tracked]);
    if (!isPdf(file)) {
      update(id, { state: "rejected", failure: NOT_A_PDF });
      return;
    }
    const result = await uploadDocument(file, {
      onProgress: (sentFraction) => update(id, { sentFraction }),
    });
    if (result.ok) {
      update(id, {
        state: "accepted",
        documentId: result.data.document_id,
        alreadyIngested: result.data.already_ingested,
      });
      onAccepted();
    } else {
      update(id, { state: result.failure.state, failure: result.failure });
    }
  };

  // An accepted upload leaves the list once its document shows in the library.
  const listed = new Set(documents.map((document) => document.id));
  const visible = uploads.filter(
    (upload) =>
      !(
        upload.state === "accepted" &&
        !upload.alreadyIngested &&
        upload.documentId !== null &&
        listed.has(upload.documentId)
      ),
  );
  const dismiss = (id: string) =>
    setUploads((current) => current.filter((upload) => upload.id !== id));

  return (
    <div className="flex flex-col gap-2">
      <input
        ref={input}
        type="file"
        accept="application/pdf,.pdf"
        multiple
        aria-label="Upload a PDF"
        className="hidden"
        onChange={(event) => {
          const files = [...(event.currentTarget.files ?? [])];
          event.currentTarget.value = "";
          for (const file of files) void send(file);
        }}
      />
      <Button
        ref={button}
        variant="outline"
        className="w-full"
        onClick={openFilePicker}
      >
        <UploadIcon aria-hidden="true" />
        Upload a PDF
      </Button>
      {visible.length > 0 && (
        <ul aria-label="Uploads" className="flex flex-col gap-2">
          {visible.map((upload) => (
            <li key={upload.id} className="flex flex-col gap-1.5 text-xs">
              <UploadRow
                upload={upload}
                documents={documents}
                onRetry={() => void send(upload.file, upload.id)}
                onDismiss={() => dismiss(upload.id)}
              />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function UploadRow({
  upload,
  documents,
  onRetry,
  onDismiss,
}: {
  upload: TrackedUpload;
  documents: readonly DocumentBody[];
  onRetry: () => void;
  onDismiss: () => void;
}) {
  const name = upload.file.name;
  if (upload.state === "sending") {
    return (
      <>
        <span className="truncate" title={name}>
          Sending {name}
        </span>
        <Progress
          value={Math.round(upload.sentFraction * 100)}
          aria-label={`Sending ${name}`}
        />
      </>
    );
  }
  if (upload.state === "accepted") {
    const existing = documents.find((document) => document.id === upload.documentId);
    return (
      <div className="flex items-start gap-2 rounded-md border bg-muted/40 px-2.5 py-2">
        <CheckIcon
          aria-hidden="true"
          className="mt-0.5 size-3.5 shrink-0 text-emerald-700"
        />
        <span className="min-w-0 flex-1 leading-5">
          {upload.alreadyIngested
            ? `Already ingested: ${existing?.file_name ?? name} is in the library.`
            : `${name} was received and is waiting to be processed.`}
        </span>
        <Button
          variant="ghost"
          size="icon-xs"
          aria-label={`Dismiss ${name}`}
          onClick={onDismiss}
        >
          <XIcon aria-hidden="true" />
        </Button>
      </div>
    );
  }
  return (
    <>
      <span className="truncate font-medium" title={name}>
        {name}
      </span>
      <FailureNotice
        message={upload.failure?.message ?? ""}
        reference={upload.failure?.reference ?? null}
        action={
          upload.failure?.action === "upload_again"
            ? { label: "Upload again", onAction: onRetry }
            : { label: "Dismiss", onAction: onDismiss }
        }
      />
    </>
  );
}
