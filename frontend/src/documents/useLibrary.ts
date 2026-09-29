import {
  useInfiniteQuery,
  useQueries,
  useQueryClient,
  type InfiniteData,
} from "@tanstack/react-query";
import { useCallback, useMemo } from "react";

import { callService, type ServiceFailure } from "@/api/http";
import {
  getDocument,
  listDocuments,
  type DocumentBody,
  type DocumentPageBody,
} from "@/client";
import { useConfig } from "@/config";

/** Documents listed per page (research section 6). */
export const LIBRARY_PAGE_SIZE = 50;

/** Query key of the document library. */
export const LIBRARY_KEY = ["documents"] as const;

/** A failed library call, thrown so TanStack Query retries it with backoff. */
export class LibraryError extends Error {
  override name = "LibraryError";
  readonly failure: ServiceFailure;

  constructor(failure: ServiceFailure) {
    super(`The library call failed: ${failure.kind}`);
    this.failure = failure;
  }
}

/** The document library and what can be done with it. */
export interface Library {
  /** Every loaded document, newest first, with its latest status. */
  documents: DocumentBody[];
  isLoading: boolean;
  /** Whether the service holds more documents than are loaded (FR-033). */
  hasMore: boolean;
  loadMore: () => Promise<unknown>;
  /** Read the library again, as after an upload. */
  refresh: () => Promise<unknown>;
  /** Drop a deleted document from the list at once, then read the library again. */
  remove: (documentId: string) => Promise<unknown>;
}

function unfinished(document: DocumentBody): boolean {
  const status = document.latest_job?.status;
  return status === undefined || status === "pending" || status === "processing";
}

/**
 * The document library, following every pending or processing document until it is
 * completed or failed (FR-033 to FR-035, research section 6).
 *
 * @returns The documents and the actions on the library.
 */
export function useLibrary(): Library {
  const { statusPollSeconds } = useConfig();
  const queryClient = useQueryClient();

  const library = useInfiniteQuery({
    queryKey: LIBRARY_KEY,
    initialPageParam: null as string | null,
    queryFn: async ({ pageParam }) => {
      const result = await callService((options) =>
        listDocuments({
          ...options,
          query: {
            limit: LIBRARY_PAGE_SIZE,
            ...(pageParam === null ? {} : { cursor: pageParam }),
          },
        }),
      );
      if (!result.ok) throw new LibraryError(result.failure);
      return result.data;
    },
    getNextPageParam: (page: DocumentPageBody) => page.next_cursor,
    // Retried until the service answers, with the connection notice meanwhile.
    retry: true,
    retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 10_000),
  });

  const documents = useMemo(
    () => library.data?.pages.flatMap((page) => page.items) ?? [],
    [library.data],
  );
  const followed = documents.filter(unfinished).map((document) => document.id);

  useQueries({
    queries: followed.map((documentId) => ({
      queryKey: [...LIBRARY_KEY, documentId],
      refetchInterval: statusPollSeconds * 1000,
      queryFn: async () => {
        const result = await callService((options) =>
          getDocument({ ...options, path: { document_id: documentId } }),
        );
        if (!result.ok) throw new LibraryError(result.failure);
        // The list shows the latest status, so polling stops once it is final.
        queryClient.setQueryData<InfiniteData<DocumentPageBody>>(LIBRARY_KEY, (data) =>
          data === undefined
            ? data
            : {
                ...data,
                pages: data.pages.map((page) => ({
                  ...page,
                  items: page.items.map((item) =>
                    item.id === documentId ? result.data : item,
                  ),
                })),
              },
        );
        return result.data;
      },
    })),
  });

  const { fetchNextPage, refetch } = library;
  const loadMore = useCallback(() => fetchNextPage(), [fetchNextPage]);
  const refresh = useCallback(() => refetch(), [refetch]);
  const remove = useCallback(
    (documentId: string) => {
      queryClient.setQueryData<InfiniteData<DocumentPageBody>>(LIBRARY_KEY, (data) =>
        data === undefined
          ? data
          : {
              ...data,
              pages: data.pages.map((page) => ({
                ...page,
                items: page.items.filter((item) => item.id !== documentId),
              })),
            },
      );
      return refetch();
    },
    [queryClient, refetch],
  );
  return {
    documents,
    isLoading: library.isPending,
    hasMore: library.hasNextPage,
    loadMore,
    refresh,
    remove,
  };
}
