"use client";

import { useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  createConversation,
  createProject,
  deleteConversation,
  deleteProject,
  listConversations,
  listMessages,
  listProjects,
  updateConversation,
} from "@/lib/api";
import type { WorkbenchMessage } from "@/lib/types";

export const workbenchQueryKeys = {
  projects: ["workbench", "projects"] as const,
  recentConversations: ["workbench", "conversations", "recent"] as const,
  projectConversations: (projectId: string) => ["workbench", "conversations", "project", projectId] as const,
  messages: (conversationId: string) => ["workbench", "messages", conversationId] as const,
};

export function useWorkbenchData({ enabled, projectId, conversationId }: { enabled: boolean; projectId: string | null; conversationId: string | null }) {
  const queryClient = useQueryClient();
  const projectsQuery = useQuery({ queryKey: workbenchQueryKeys.projects, queryFn: listProjects, enabled });
  const recentConversationsQuery = useQuery({ queryKey: workbenchQueryKeys.recentConversations, queryFn: () => listConversations(), enabled });
  const projectConversationsQuery = useQuery({
    queryKey: workbenchQueryKeys.projectConversations(projectId ?? ""),
    queryFn: () => listConversations(projectId!),
    enabled: enabled && Boolean(projectId),
  });
  const messagesQuery = useQuery({
    queryKey: workbenchQueryKeys.messages(conversationId ?? ""),
    queryFn: () => listMessages(conversationId!),
    enabled: enabled && Boolean(conversationId),
  });

  const refreshProjects = useCallback(
    () => queryClient.fetchQuery({ queryKey: workbenchQueryKeys.projects, queryFn: listProjects, staleTime: 0 }),
    [queryClient],
  );
  const refreshConversations = useCallback(
    async (nextProjectId: string | null) => {
      const [projectConversations, recentConversations] = await Promise.all([
        nextProjectId
          ? queryClient.fetchQuery({ queryKey: workbenchQueryKeys.projectConversations(nextProjectId), queryFn: () => listConversations(nextProjectId), staleTime: 0 })
          : Promise.resolve([]),
        queryClient.fetchQuery({ queryKey: workbenchQueryKeys.recentConversations, queryFn: () => listConversations(), staleTime: 0 }),
      ]);
      return { projectConversations, recentConversations };
    },
    [queryClient],
  );
  const refreshMessages = useCallback(
    (nextConversationId: string) => queryClient.fetchQuery({ queryKey: workbenchQueryKeys.messages(nextConversationId), queryFn: () => listMessages(nextConversationId), staleTime: 0 }),
    [queryClient],
  );
  const updateMessages = useCallback(
    (targetConversationId: string, updater: (messages: WorkbenchMessage[]) => WorkbenchMessage[]) => {
      queryClient.setQueryData<WorkbenchMessage[]>(workbenchQueryKeys.messages(targetConversationId), (current) => updater(current ?? []));
    },
    [queryClient],
  );
  const clear = useCallback(() => queryClient.removeQueries({ queryKey: ["workbench"] }), [queryClient]);

  const createProjectMutation = useMutation({
    mutationFn: createProject,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: workbenchQueryKeys.projects }),
  });
  const deleteProjectMutation = useMutation({
    mutationFn: deleteProject,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["workbench", "projects"] }),
  });
  const createConversationMutation = useMutation({
    mutationFn: createConversation,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["workbench", "conversations"] }),
  });
  const deleteConversationMutation = useMutation({
    mutationFn: deleteConversation,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["workbench", "conversations"] }),
  });
  const updateConversationMutation = useMutation({
    mutationFn: ({ id, ...input }: { id: string } & Parameters<typeof updateConversation>[1]) =>
      updateConversation(id, input),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["workbench", "conversations"] }),
  });

  return {
    projects: projectsQuery.data ?? [],
    projectConversations: projectConversationsQuery.data ?? [],
    recentConversations: recentConversationsQuery.data ?? [],
    messages: messagesQuery.data ?? [],
    refreshProjects,
    refreshConversations,
    refreshMessages,
    updateMessages,
    clear,
    createProject: createProjectMutation.mutateAsync,
    deleteProject: deleteProjectMutation.mutateAsync,
    createConversation: createConversationMutation.mutateAsync,
    deleteConversation: deleteConversationMutation.mutateAsync,
    updateConversation: updateConversationMutation.mutateAsync,
  };
}
