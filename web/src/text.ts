export const sentence = (text: string): string =>
  text ? text.charAt(0).toUpperCase() + text.slice(1) : text;

export const plural = (count: number, word: string): string =>
  `${count} ${word}${count === 1 ? "" : "s"}`;
