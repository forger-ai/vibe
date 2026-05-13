/* eslint-disable react-refresh/only-export-components */
import {
  createContext,
  type ReactNode,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { en } from "./en";
import { es } from "./es";

export type Locale = "es" | "en";
type Widen<T> = T extends (...args: infer Args) => infer Return
  ? (...args: Args) => Return
  : T extends string
    ? string
    : T extends number
      ? number
      : T extends boolean
        ? boolean
        : T extends readonly (infer Item)[]
          ? readonly Widen<Item>[]
          : { [K in keyof T]: Widen<T[K]> };

export type Dictionary = Widen<typeof es>;

const dictionaries: Record<Locale, Dictionary> = { es, en };
const I18nContext = createContext<Dictionary>(es);
const LocaleContext = createContext<Locale>("es");

function normalizeLocale(value: string | null | undefined): Locale {
  const normalized = (value ?? "").toLowerCase();
  return normalized === "en" || normalized.startsWith("en-") ? "en" : "es";
}

function browserLocale(): Locale {
  if (typeof navigator === "undefined") return "es";
  for (const language of navigator.languages ?? []) {
    if (normalizeLocale(language) === "en") return "en";
  }
  return normalizeLocale(navigator.language);
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocale] = useState<Locale>(browserLocale);

  useEffect(() => {
    let active = true;
    void window.forgerApp
      ?.getContext?.()
      .then((context) => {
        if (active) setLocale(normalizeLocale(context?.locale));
      })
      .catch(() => {
        if (active) setLocale(browserLocale());
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);

  const value = useMemo(() => dictionaries[locale] ?? es, [locale]);

  return (
    <LocaleContext.Provider value={locale}>
      <I18nContext.Provider value={value}>{children}</I18nContext.Provider>
    </LocaleContext.Provider>
  );
}

export function useI18n(): Dictionary {
  return useContext(I18nContext);
}

export function useLocale(): Locale {
  return useContext(LocaleContext);
}
