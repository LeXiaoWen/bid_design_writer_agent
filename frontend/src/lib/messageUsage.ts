const CONTEXT_CHARACTER_BUDGET = 24_000;

type Usage = Record<string, unknown> | null | undefined;

function usageValue(usage: Usage, key: string): number | null {
  const value = usage?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function usageText(usage: Usage, key: string): string | null {
  const value = usage?.[key];
  return typeof value === "string" ? value : null;
}

export function formatMessageUsage(usage: Usage, estimatedContextCharacters: number): string {
  const totalTokens = usageValue(usage, "total_tokens");
  const contextCharacters = usageValue(usage, "context_characters");
  const contextBudget = usageValue(usage, "context_budget") ?? CONTEXT_CHARACTER_BUDGET;
  const contextTokens = usageValue(usage, "context_estimated_tokens");
  const completionTokens = usageValue(usage, "completion_estimated_tokens");
  const totalEstimatedTokens = usageValue(usage, "total_estimated_tokens");
  const isSkillEstimate = usageText(usage, "usage_source") === "estimated";
  const hasServerContext = contextCharacters !== null;
  const characters = contextCharacters ?? Math.min(estimatedContextCharacters, CONTEXT_CHARACTER_BUDGET);
  const estimatedTokens = contextTokens ?? Math.ceil(characters / 4);
  const contextLabel = isSkillEstimate ? "Skill 上下文" : hasServerContext ? "上下文" : "上下文本地估算";
  const contextText = isSkillEstimate ? `${characters.toLocaleString()} 字符` : `${characters.toLocaleString()}/${contextBudget.toLocaleString()} 字符`;
  if (isSkillEstimate) {
    const outputLabel = completionTokens !== null ? `输出约 ${completionTokens.toLocaleString()} tokens` : null;
    const totalLabel = totalEstimatedTokens !== null ? `总计约 ${totalEstimatedTokens.toLocaleString()} tokens` : `输入约 ${estimatedTokens.toLocaleString()} tokens`;
    return [contextLabel + " " + contextText, `输入约 ${estimatedTokens.toLocaleString()} tokens`, outputLabel, totalLabel].filter(Boolean).join(" · ");
  }
  const tokenLabel = totalTokens !== null ? `实际 ${totalTokens.toLocaleString()} tokens` : `约 ${estimatedTokens.toLocaleString()} tokens`;

  return `${contextLabel} ${contextText} · ${tokenLabel}`;
}
