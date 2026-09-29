import { http, HttpResponse } from "msw";

import { ConfigError, loadConfig } from "@/config";

import { defaultConfig } from "../tests/msw/handlers";
import { server } from "../tests/msw/server";

function serveConfig(body: Record<string, unknown>): void {
  server.use(http.get("/config.json", () => HttpResponse.json(body)));
}

test("a valid config.json loads into the runtime configuration", async () => {
  await expect(loadConfig()).resolves.toEqual(defaultConfig);
});

test("an unreachable config.json fails with a typed error", async () => {
  server.use(http.get("/config.json", () => HttpResponse.error()));

  await expect(loadConfig()).rejects.toBeInstanceOf(ConfigError);
});

test.each([
  ["a missing field", { answerWaitSeconds: 105, statusPollSeconds: 2 }],
  ["a zero wait limit", { ...defaultConfig, answerWaitSeconds: 0 }],
  ["a negative poll interval", { ...defaultConfig, statusPollSeconds: -1 }],
  ["a fractional document limit", { ...defaultConfig, maxFilterDocuments: 1.5 }],
  ["a zero document limit", { ...defaultConfig, maxFilterDocuments: 0 }],
  ["a string instead of a number", { ...defaultConfig, answerWaitSeconds: "105" }],
])("config.json with %s is refused", async (_case, body) => {
  serveConfig(body);

  await expect(loadConfig()).rejects.toBeInstanceOf(ConfigError);
});

test("config.json answered with an error status is refused", async () => {
  server.use(http.get("/config.json", () => new HttpResponse(null, { status: 404 })));

  await expect(loadConfig()).rejects.toBeInstanceOf(ConfigError);
});
