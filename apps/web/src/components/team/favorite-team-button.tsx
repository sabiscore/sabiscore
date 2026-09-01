"use client";

import React from "react";
import { Heart } from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import { cn } from "@/lib/utils";

interface FavoriteTeamButtonProps {
  slug: string;
  teamName: string;
}

export function FavoriteTeamButton({ slug, teamName }: FavoriteTeamButtonProps) {
  const { isFavorite, toggleFavorite } = useAuth();
  const favorite = isFavorite(slug);

  return (
    <button
      type="button"
      onClick={() => toggleFavorite("team", slug)}
      className={cn(
        "flex min-h-9 items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-semibold transition focus:outline-none focus:ring-2 focus:ring-emerald-400",
        favorite
          ? "border-rose-500/40 bg-rose-500/20 text-rose-300"
          : "border-zinc-700 bg-zinc-800/50 text-zinc-300 hover:bg-zinc-700 hover:text-white"
      )}
      aria-label={favorite ? `Remove ${teamName} from favorites` : `Add ${teamName} to favorites`}
    >
      <Heart className={cn("h-3.5 w-3.5", favorite && "fill-rose-400 text-rose-400")} />
      <span>{favorite ? "Favorited" : "Favorite Team"}</span>
    </button>
  );
}

export default FavoriteTeamButton;
