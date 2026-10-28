/**
 * Texts from the analysis service (limitations, coverage reasons, notices) are already in
 * Indonesian and are shown as returned. The UI writes its own primary wording; these texts
 * appear in secondary "catatan" sections. Kept as one function so callers stay unchanged.
 */
export function serviceText(text: string, _attribute: (name: string) => string = name => name): string {
  return text;
}
