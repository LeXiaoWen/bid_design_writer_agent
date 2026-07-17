"use client";

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { getBidWorkflow, listBidWorkflows } from "@/lib/api";
import type { BidWorkflow } from "@/lib/types";

function isRunning(workflow: BidWorkflow | null): boolean {
  return workflow?.status === "extracting" || workflow?.status === "generating";
}

export function useBidWorkflow() {
  const [workflow, setWorkflow] = useState<BidWorkflow | null>(null);
  const [isBusy, setIsBusy] = useState(false);

  const query = useQuery({
    queryKey: ["bid-workflow", workflow?.id],
    queryFn: () => getBidWorkflow(workflow!.id),
    enabled: Boolean(workflow?.id),
    // The cached response may still be the pre-action "uploaded" state. Prefer the
    // action response held in local state so polling starts immediately.
    refetchInterval: () => (isRunning(workflow) ? 500 : false),
  });

  useEffect(() => {
    if (!query.data) return;
    setWorkflow(query.data);
    setIsBusy(isRunning(query.data));
  }, [query.data]);

  return {
    workflow,
    setWorkflow,
    isBusy,
    setIsBusy,
    polledWorkflow: query.data,
    error: query.error,
  };
}

export function useBidWorkflows(conversationId: string | null, knownWorkflows: BidWorkflow[]) {
  const query = useQuery({
    queryKey: ["bid-workflows", conversationId],
    queryFn: () => listBidWorkflows(conversationId!),
    enabled: Boolean(conversationId),
    refetchInterval: (current) => (
      knownWorkflows.some((workflow) => isRunning(workflow)) || current.state.data?.some((workflow) => isRunning(workflow)) ? 500 : false
    ),
  });

  return { workflows: query.data, error: query.error };
}
