import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import en from "./en";
import sv from "./sv";
import type { I18nKey, Locale } from "./types";

const DICTS: Record<Locale, Partial<Record<I18nKey, string>>> = { sv, en };
const STORAGE_KEY = "myggprognos.locale";
const DEFAULT_LOCALE: Locale = "sv";

function readStoredLocale(): Locale {
  if (typeof window === "undefined") return DEFAULT_LOCALE;
  const stored = window.localStorage.getItem(STORAGE_KEY);
  return stored === "en" || stored === "sv" ? stored : DEFAULT_LOCALE;
}

function interpolate(template: string, vars?: Record<string, string | number>): string {
  if (!vars) return template;
  return template.replace(/\{(\w+)\}/g, (match, key: string) => {
    const value = vars[key];
    return value === undefined ? match : String(value);
  });
}

interface I18nContextValue {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: (key: I18nKey, vars?: Record<string, string | number>) => string;
}

const I18nContext = createContext<I18nContextValue | null>(null);

export function LocaleProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(readStoredLocale);

  const setLocale = useCallback((next: Locale) => {
    setLocaleState(next);
    if (typeof window !== "undefined") window.localStorage.setItem(STORAGE_KEY, next);
  }, []);

  const t = useCallback(
    (key: I18nKey, vars?: Record<string, string | number>) => {
      const template = DICTS[locale][key] ?? sv[key] ?? key;
      return interpolate(template, vars);
    },
    [locale]
  );

  const value = useMemo(() => ({ locale, setLocale, t }), [locale, setLocale, t]);

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nContextValue {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error("useI18n() must be used within a <LocaleProvider>");
  return ctx;
}
