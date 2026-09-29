import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, type RenderResult } from "@testing-library/react";
import type { ReactNode } from "react";

import { TooltipProvider } from "@/components/ui/tooltip";
import { ConfigContext, type RuntimeConfig } from "@/config";

import { defaultConfig } from "./msw/handlers";

/**
 * Render inside the providers the application sets up, with a fresh query cache.
 *
 * @param ui - Element to render.
 * @param config - Runtime configuration overrides.
 * @returns Testing Library's render result.
 */
export function renderWithProviders(
  ui: ReactNode,
  config: Partial<RuntimeConfig> = {},
): RenderResult {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <ConfigContext value={{ ...defaultConfig, ...config }}>
      <QueryClientProvider client={queryClient}>
        <TooltipProvider>{ui}</TooltipProvider>
      </QueryClientProvider>
    </ConfigContext>,
  );
}
