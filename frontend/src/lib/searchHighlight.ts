export type SearchHighlightPart = {
  text: string;
  matched: boolean;
};

export function splitSearchHighlight(text: string, query: string): SearchHighlightPart[] {
  const keyword = query.trim();
  if (!keyword) return [{ text, matched: false }];

  const normalizedText = text.toLocaleLowerCase();
  const normalizedKeyword = keyword.toLocaleLowerCase();
  const parts: SearchHighlightPart[] = [];
  let cursor = 0;
  let matchIndex = normalizedText.indexOf(normalizedKeyword, cursor);
  while (matchIndex >= 0) {
    if (matchIndex > cursor) parts.push({ text: text.slice(cursor, matchIndex), matched: false });
    parts.push({ text: text.slice(matchIndex, matchIndex + keyword.length), matched: true });
    cursor = matchIndex + keyword.length;
    matchIndex = normalizedText.indexOf(normalizedKeyword, cursor);
  }
  if (cursor < text.length) parts.push({ text: text.slice(cursor), matched: false });
  return parts.length > 0 ? parts : [{ text, matched: false }];
}
