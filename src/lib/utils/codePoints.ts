/**
 * Engine spans are Unicode code-point offsets; a textarea's selection is in
 * UTF-16 code units. They differ once an astral-plane character (an emoji, a
 * rare CJK or historic-script letter) precedes the offset.
 */
export function codePointToUtf16(text: string, codePointOffset: number): number {
  let units = 0;
  let points = 0;
  for (const char of text) {
    if (points >= codePointOffset) break;
    units += char.length;
    points += 1;
  }
  return units;
}
