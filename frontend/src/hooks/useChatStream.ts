"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { streamChat } from "@/lib/api";
import type { ChatStreamEvent } from "@/lib/types";

type ChatInput = Parameters<typeof streamChat>[0];

export function useChatStream() {
  const abortRef = useRef<AbortController | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);

  const send = useCallback(async (input: ChatInput, onEvent: (event: ChatStreamEvent) => void) => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setIsStreaming(true);
    try {
      await streamChat(input, onEvent, controller.signal);
    } finally {
      if (abortRef.current === controller) {
        abortRef.current = null;
        setIsStreaming(false);
      }
    }
  }, []);

  const abort = useCallback(() => abortRef.current?.abort(), []);

  useEffect(() => abort, [abort]);
  return { isStreaming, send, abort };
}
