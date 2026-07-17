DOCUMENT_CHUNK_CHARACTER_BUDGET = 24_000


def split_document_text(text: str, max_characters: int = DOCUMENT_CHUNK_CHARACTER_BUDGET) -> list[str]:
    if len(text) <= max_characters:
        return [text]

    chunks = []
    remaining = text
    while len(remaining) > max_characters:
        cut = _find_chunk_boundary(remaining, max_characters)
        chunks.append(remaining[:cut])
        remaining = remaining[cut:]
    if remaining:
        chunks.append(remaining)
    return chunks


def _find_chunk_boundary(text: str, max_characters: int) -> int:
    for boundary in ("\n\n---", "\n\n", "\n"):
        cut = text.rfind(boundary, 1, max_characters + 1)
        if cut > 0:
            return cut
    return max_characters
