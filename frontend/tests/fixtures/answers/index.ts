import { zAnswerBody } from "@/client/zod.gen";
import type { AnswerBody } from "@/client";

// Every JSON file of this directory, validated against the contract's schema, so a
// fixture that drifts from the contract fails the tests that load it.
const files = import.meta.glob<unknown>("./*.json", { eager: true, import: "default" });

/** The reference answer set: captured responses and ones written to the contract. */
export const referenceAnswers: ReadonlyArray<{ name: string; response: AnswerBody }> =
  Object.entries(files)
    .map(([path, body]) => ({
      name: path.replace(/^\.\//, "").replace(/\.json$/, ""),
      response: zAnswerBody.parse(body) as AnswerBody,
    }))
    .sort((a, b) => a.name.localeCompare(b.name));

/** The answered responses of the reference set. */
export const answeredReferences = referenceAnswers.filter(
  ({ response }) => response.status === "answered",
);
