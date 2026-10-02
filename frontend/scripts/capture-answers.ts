/**
 * Record reference answers from a running system into tests/fixtures/answers/.
 *
 * Run with Node's built-in type stripping:
 *   BASE_URL=http://localhost:3000 node scripts/capture-answers.ts
 */
import { mkdir, readFile, writeFile } from "node:fs/promises";

interface ReferenceQuestion {
  slug: string;
  question: string;
  document_ids?: string[];
}

// Where the running system is, and where the questions and answers live
const baseUrl = process.env["BASE_URL"] ?? "http://localhost:3000";
const questionsFile = new URL("./reference-questions.json", import.meta.url);
const outputDirectory = new URL("../tests/fixtures/answers/", import.meta.url);

// Load the reference questions and make sure the output folder exists
const questions = JSON.parse(
  await readFile(questionsFile, "utf8"),
) as ReferenceQuestion[];
await mkdir(outputDirectory, { recursive: true });

// Ask each question in turn and save the raw answer as a fixture
for (const { slug, question, document_ids } of questions) {
  const started = performance.now();
  const response = await fetch(new URL("/api/v1/questions", baseUrl), {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Request-ID": `capture-${slug}` },
    body: JSON.stringify(document_ids ? { question, document_ids } : { question }),
  });
  const body: unknown = await response.json();
  const seconds = ((performance.now() - started) / 1000).toFixed(1);

  // A failed question is reported and skipped
  if (!response.ok) {
    console.error(`${slug}: ${response.status} after ${seconds} s`);
    continue;
  }
  await writeFile(
    new URL(`${slug}.json`, outputDirectory),
    `${JSON.stringify(body, null, 2)}\n`,
  );
  console.log(`${slug}: captured in ${seconds} s`);
}
