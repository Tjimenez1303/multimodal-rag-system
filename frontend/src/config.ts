import { createContext, useContext } from "react";
import { z } from "zod";

/** Runtime configuration served by nginx at `/config.json` (contracts/client.md section 1). */
export interface RuntimeConfig {
  /** Longest wait for an answer, above the service's own deadline. */
  answerWaitSeconds: number;
  /** Most documents a question can be restricted to. */
  maxFilterDocuments: number;
  /** Interval between status checks of unfinished documents. */
  statusPollSeconds: number;
}

// Validation rules of each field
const runtimeConfigSchema = z.object({
  answerWaitSeconds: z.number().positive(),
  maxFilterDocuments: z.number().int().min(1),
  statusPollSeconds: z.number().positive(),
});

// Same limit as every other service call (research section 5).
const CONFIG_TIMEOUT_MS = 10_000;

/** The runtime configuration could not be loaded or is invalid. */
export class ConfigError extends Error {
  override name = "ConfigError";
}

/**
 * Fetch and validate the runtime configuration.
 *
 * @returns The validated configuration.
 * @throws {ConfigError} When `/config.json` is unreachable, times out or is invalid.
 */
export async function loadConfig(): Promise<RuntimeConfig> {
  let body: unknown;
  try {
    // Fetch the file fresh on every load, within the timeout
    const response = await fetch(new URL("/config.json", window.location.origin), {
      cache: "no-store",
      signal: AbortSignal.timeout(CONFIG_TIMEOUT_MS),
    });
    if (!response.ok) {
      throw new ConfigError(`config.json answered ${response.status}`);
    }
    body = await response.json();
  } catch (error) {
    // Any network or parsing error becomes a ConfigError
    if (error instanceof ConfigError) throw error;
    throw new ConfigError("config.json could not be loaded", { cause: error });
  }

  // Validate the values before the app relies on them
  const parsed = runtimeConfigSchema.safeParse(body);
  if (!parsed.success) {
    throw new ConfigError("config.json is invalid", { cause: parsed.error });
  }
  return parsed.data;
}

/** Provides the loaded runtime configuration to the application. */
export const ConfigContext = createContext<RuntimeConfig | null>(null);

/**
 * Read the runtime configuration.
 *
 * @returns The configuration loaded at start.
 * @throws {Error} When used outside `ConfigContext`.
 */
export function useConfig(): RuntimeConfig {
  const config = useContext(ConfigContext);

  // Fail loudly when a component renders outside the provider
  if (config === null) {
    throw new Error("useConfig must be used inside ConfigContext");
  }
  return config;
}
