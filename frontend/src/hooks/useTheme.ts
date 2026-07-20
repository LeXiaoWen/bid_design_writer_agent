"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { activateTheme, deleteTheme, downloadThemeImage, listThemes, uploadTheme } from "@/lib/api";
import { analyzeThemeImage, deriveThemePresentation, type ThemePresentation } from "@/lib/themeAnalysis";
import type { ThemeAppearance, UserTheme } from "@/lib/types";

const queryKey = ["themes"] as const;

export function useTheme(enabled: boolean) {
  const client = useQueryClient();
  const themesQuery = useQuery({ queryKey, queryFn: listThemes, enabled });
  const activeTheme = useMemo(() => themesQuery.data?.themes.find((theme) => theme.id === themesQuery.data?.active_theme_id) ?? themesQuery.data?.themes[0] ?? null, [themesQuery.data]);
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [presentation, setPresentation] = useState<ThemePresentation>(() => deriveThemePresentation({ r: 91, g: 123, b: 141 }, "light"));

  useEffect(() => {
    let revokedUrl: string | null = null;
    if (!activeTheme?.image_url) {
      setImageUrl(null);
      setPresentation(deriveThemePresentation({ r: 91, g: 123, b: 141 }, "light"));
      return undefined;
    }
    let settled = false;
    void downloadThemeImage(activeTheme.image_url).then(async (blob) => {
      const nextUrl = URL.createObjectURL(blob);
      revokedUrl = nextUrl;
      settled = true;
      setImageUrl(nextUrl);
      try {
        setPresentation(await analyzeThemeImage(nextUrl, activeTheme.appearance));
      } catch {
        setPresentation(deriveThemePresentation({ r: 91, g: 123, b: 141 }, "light"));
      }
    }).catch(() => {
      if (!settled) setImageUrl(null);
    });
    return () => { if (revokedUrl) URL.revokeObjectURL(revokedUrl); };
  }, [activeTheme?.appearance, activeTheme?.id, activeTheme?.image_url]);

  const invalidate = () => client.invalidateQueries({ queryKey });
  const upload = useMutation({ mutationFn: uploadTheme, onSuccess: invalidate });
  const activate = useMutation({ mutationFn: activateTheme, onSuccess: (data) => client.setQueryData(queryKey, data) });
  const remove = useMutation({ mutationFn: deleteTheme, onSuccess: invalidate });

  return {
    themes: themesQuery.data?.themes ?? [],
    activeTheme,
    imageUrl,
    presentation,
    isLoading: themesQuery.isLoading,
    upload: (file: File, appearance: ThemeAppearance) => upload.mutateAsync({ file, appearance }),
    activate: (themeId: string) => activate.mutateAsync(themeId),
    remove: (themeId: string) => remove.mutateAsync(themeId),
    isBusy: upload.isPending || activate.isPending || remove.isPending,
  };
}
