"use client";

import { useQuery } from "@tanstack/react-query";

import { listProviderModels } from "@/lib/api";

export function useProviderModels(profileId: string | null, enabled: boolean) {
  const query = useQuery({
    queryKey: ["provider-models", profileId],
    queryFn: () => listProviderModels(profileId!),
    enabled: Boolean(profileId && enabled),
    retry: false,
    staleTime: 5 * 60 * 1000,
  });

  return {
    models: query.data ?? [],
    isLoading: query.isLoading,
    error: query.error,
  };
}
