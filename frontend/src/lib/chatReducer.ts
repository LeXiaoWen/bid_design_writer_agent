import type { ChatStreamEvent, WorkbenchMessage } from "./types";

export function applyChatStreamEvent(messages: WorkbenchMessage[], event: ChatStreamEvent, now = new Date().toISOString()): WorkbenchMessage[] {
  if (event.event === "message_start") {
    if (messages.some((message) => message.id === event.data.message_id)) return messages;
    return [
      ...messages,
      {
        id: event.data.message_id,
        conversation_id: event.data.conversation_id,
        role: "assistant",
        content: "",
        status: "streaming",
        model: event.data.model,
        usage: event.data.usage,
        created_at: now,
        updated_at: now,
      },
    ];
  }

  if (event.event === "delta") {
    return messages.map((message) =>
      message.id === event.data.message_id ? { ...message, content: `${message.content}${event.data.delta}`, updated_at: now } : message,
    );
  }

  if (event.event === "message_done") {
    return messages.map((message) =>
      message.id === event.data.message_id
        ? {
            ...message,
            content: event.data.content,
            status: event.data.status,
            finish_reason: event.data.finish_reason,
            usage: event.data.usage ?? message.usage,
            updated_at: now,
          }
        : message,
    );
  }

  if (event.event === "error" && event.data.message_id) {
    return messages.map((message) =>
      message.id === event.data.message_id
        ? {
            ...message,
            content: event.data.content ?? message.content,
            status: "error",
            error: event.data.message,
            updated_at: now,
          }
        : message,
    );
  }

  return messages;
}
