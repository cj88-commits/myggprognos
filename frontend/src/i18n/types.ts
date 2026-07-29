import type sv from "./sv";

export type I18nKey = keyof typeof sv;
// Widened to `string` values (not the literal Swedish strings) so other
// locale dictionaries can hold their own translated text for the same keys.
export type I18nDict = Record<I18nKey, string>;
export type Locale = "sv" | "en";
