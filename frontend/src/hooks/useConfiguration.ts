"use client";

import { useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  createProviderProfile,
  getWebSearchConfig,
  listProviderProfiles,
  updateProviderProfile,
  updateWebSearchConfig,
} from "@/lib/api";

export const configurationQueryKeys = {
  profiles: ["configuration", "provider-profiles"] as const,
  webSearch: ["configuration", "web-search"] as const,
};

type ProviderProfileInput = Parameters<typeof createProviderProfile>[0];
type ProviderProfileUpdate = Parameters<typeof updateProviderProfile>[1];
type WebSearchInput = Parameters<typeof updateWebSearchConfig>[0];

export function useConfiguration(enabled: boolean) {
  const queryClient = useQueryClient();
  const profilesQuery = useQuery({ queryKey: configurationQueryKeys.profiles, queryFn: listProviderProfiles, enabled });
  const webSearchQuery = useQuery({ queryKey: configurationQueryKeys.webSearch, queryFn: getWebSearchConfig, enabled });

  const createProfileMutation = useMutation({
    mutationFn: createProviderProfile,
    onSuccess: (profile) => queryClient.setQueryData(configurationQueryKeys.profiles, (profiles: typeof profilesQuery.data) => [...(profiles ?? []), profile]),
  });
  const updateProfileMutation = useMutation({
    mutationFn: ({ profileId, input }: { profileId: string; input: ProviderProfileUpdate }) => updateProviderProfile(profileId, input),
    onSuccess: (profile) => queryClient.setQueryData(configurationQueryKeys.profiles, (profiles: typeof profilesQuery.data) => (profiles ?? []).map((item) => item.id === profile.id ? profile : item)),
  });
  const updateWebSearchMutation = useMutation({
    mutationFn: updateWebSearchConfig,
    onSuccess: (config) => queryClient.setQueryData(configurationQueryKeys.webSearch, config),
  });
  const clear = useCallback(() => queryClient.removeQueries({ queryKey: ["configuration"] }), [queryClient]);

  return {
    profiles: profilesQuery.data ?? [],
    webSearchConfig: webSearchQuery.data ?? null,
    error: profilesQuery.error ?? webSearchQuery.error,
    createProfile: (input: ProviderProfileInput) => createProfileMutation.mutateAsync(input),
    updateProfile: (profileId: string, input: ProviderProfileUpdate) => updateProfileMutation.mutateAsync({ profileId, input }),
    updateWebSearch: (input: WebSearchInput) => updateWebSearchMutation.mutateAsync(input),
    clear,
  };
}
