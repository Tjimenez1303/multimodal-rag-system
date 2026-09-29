import type { AnswerBody } from "@/client";

import { referenceAnswers } from "./index";

/**
 * One response of the reference answer set, by file name.
 *
 * @param name - File name without `.json`.
 * @returns The response, validated against the contract.
 */
export function answer(name: string): AnswerBody {
  const found = referenceAnswers.find((reference) => reference.name === name);
  if (found === undefined) throw new Error(`No reference answer named ${name}`);
  return found.response;
}
