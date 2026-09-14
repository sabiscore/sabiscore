"use client";

import React, { createContext, useCallback, useContext, useEffect, useState } from "react";
import { analytics } from "@/lib/analytics";

export interface UserProfile {
  id: string;
  email: string;
  username?: string;
  full_name?: string;
  avatar_url?: string;
  email_verified?: boolean;
  is_active: boolean;
}

export interface UserFavorite {
  id: string;
  entity_type: string;
  entity_id: string;
  created_at?: string;
}

export interface SavedMatch {
  id: string;
  match_id: string;
  target_outcome?: string;
  notes?: string;
  created_at?: string;
}

export interface UserPreferences {
  odds_format: string;
  timezone: string;
  default_league?: string;
}

interface AuthResult {
  success: boolean;
  error?: string;
}

interface AuthContextType {
  user: UserProfile | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  favorites: UserFavorite[];
  savedMatches: SavedMatch[];
  preferences: UserPreferences | null;
  login: (email: string, password: string, rememberMe?: boolean) => Promise<AuthResult>;
  register: (username: string, email: string, password: string, fullName?: string) => Promise<AuthResult>;
  startGoogleSignIn: (nextPath?: string) => void;
  logout: () => Promise<void>;
  toggleFavorite: (entityType: string, entityId: string) => Promise<boolean>;
  isFavorite: (entityId: string) => boolean;
  saveMatch: (matchId: string, targetOutcome?: string, notes?: string) => Promise<boolean>;
  removeSavedMatch: (matchId: string) => Promise<boolean>;
  isMatchSaved: (matchId: string) => boolean;
  updatePreferences: (prefs: Partial<UserPreferences>) => Promise<boolean>;
  refreshState: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

function getErrorMessage(payload: unknown, fallback: string): string {
  if (!payload || typeof payload !== "object") return fallback;
  const data = payload as { detail?: unknown; message?: unknown; error?: unknown };
  if (typeof data.detail === "string") return data.detail;
  if (typeof data.message === "string") return data.message;
  if (typeof data.error === "string") return data.error;
  return fallback;
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<UserProfile | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [favorites, setFavorites] = useState<UserFavorite[]>([]);
  const [savedMatches, setSavedMatches] = useState<SavedMatch[]>([]);
  const [preferences, setPreferences] = useState<UserPreferences | null>({
    odds_format: "DECIMAL",
    timezone: "Africa/Lagos",
    default_league: "EPL",
  });

  const loadUserData = useCallback(async () => {
    try {
      const meRes = await fetch("/api/auth/me", { cache: "no-store" });
      if (meRes.ok) {
        const userData = (await meRes.json()) as UserProfile;
        setUser(userData);
      } else {
        setUser(null);
      }
    } catch {
      setUser(null);
    }

    try {
      const favRes = await fetch("/api/users/favorites", { cache: "no-store" });
      if (favRes.ok) {
        const favData = await favRes.json();
        setFavorites(Array.isArray(favData) ? favData : favData.favorites || []);
      }
    } catch {
      // Anonymous state is allowed to fail closed when the backend is unavailable.
    }

    try {
      const smRes = await fetch("/api/users/saved-matches", { cache: "no-store" });
      if (smRes.ok) {
        const smData = await smRes.json();
        setSavedMatches(Array.isArray(smData) ? smData : smData.saved_matches || []);
      }
    } catch {
      // Anonymous state is allowed to fail closed when the backend is unavailable.
    }

    try {
      const prefRes = await fetch("/api/users/preferences", { cache: "no-store" });
      if (prefRes.ok) {
        const prefData = await prefRes.json();
        if (prefData && prefData.odds_format) {
          setPreferences({
            odds_format: prefData.odds_format,
            timezone: prefData.timezone || "Africa/Lagos",
            default_league: prefData.default_league || "EPL",
          });
        }
      }
    } catch {
      // Preferences are non-critical to authentication state.
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadUserData();
  }, [loadUserData]);

  const login = useCallback(
    async (email: string, password: string, rememberMe = false): Promise<AuthResult> => {
      try {
        const res = await fetch("/api/auth/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email, password, remember_me: rememberMe }),
        });

        if (!res.ok) {
          const payload = await res.json().catch(() => null);
          return {
            success: false,
            error: getErrorMessage(payload, "Invalid email or password."),
          };
        }

        await loadUserData();
        analytics.track("dashboard_viewed", { source: "login" });
        return { success: true };
      } catch {
        return { success: false, error: "Unable to reach the authentication service." };
      }
    },
    [loadUserData],
  );

  const register = useCallback(
    async (
      username: string,
      email: string,
      password: string,
      fullName?: string,
    ): Promise<AuthResult> => {
      try {
        const res = await fetch("/api/auth/register", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            username,
            email,
            password,
            full_name: fullName?.trim() || username,
          }),
        });

        if (!res.ok) {
          const payload = await res.json().catch(() => null);
          return {
            success: false,
            error: getErrorMessage(payload, "Registration failed. Please try again."),
          };
        }

        return await login(email, password, true);
      } catch {
        return { success: false, error: "Unable to reach the authentication service." };
      }
    },
    [login],
  );

  const startGoogleSignIn = useCallback((nextPath = "/dashboard") => {
    if (typeof window === "undefined") return;

    const currentPath = `${window.location.pathname}${window.location.search}`;
    const destination = nextPath === "/dashboard" && currentPath !== "/" ? currentPath : nextPath;
    const safeDestination = destination.startsWith("/") && !destination.startsWith("//")
      ? destination
      : "/dashboard";

    window.location.assign(
      `/api/auth/google/start?next=${encodeURIComponent(safeDestination)}`,
    );
  }, []);

  const logout = useCallback(async () => {
    try {
      await fetch("/api/auth/logout", { method: "POST" });
    } catch {
      // Local state is cleared even if the backend is temporarily unreachable.
    }
    setUser(null);
    await loadUserData();
  }, [loadUserData]);

  const toggleFavorite = async (entityType: string, entityId: string): Promise<boolean> => {
    const existing = favorites.find(
      (favorite) => favorite.entity_id?.toLowerCase() === entityId.toLowerCase(),
    );

    if (existing) {
      try {
        const response = await fetch(`/api/users/favorites/${encodeURIComponent(existing.id || entityId)}`, {
          method: "DELETE",
        });
        if (response.ok) {
          setFavorites((previous) => previous.filter((favorite) => favorite.id !== existing.id && favorite.entity_id !== entityId));
          analytics.track("favorite_toggled", { entity_type: entityType, entity_id: entityId, action: "removed" });
          return true;
        }
      } catch {
        // Fall through to a failed mutation result.
      }
      return false;
    }

    try {
      const response = await fetch("/api/users/favorites", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ entity_type: entityType, entity_id: entityId }),
      });
      if (response.ok) {
        const newFavorite = await response.json();
        setFavorites((previous) => [...previous, newFavorite]);
        analytics.track("favorite_toggled", { entity_type: entityType, entity_id: entityId, action: "added" });
        return true;
      }
    } catch {
      // Fall through to a failed mutation result.
    }
    return false;
  };

  const isFavorite = (entityId: string): boolean =>
    favorites.some((favorite) => favorite.entity_id?.toLowerCase() === entityId?.toLowerCase());

  const saveMatch = async (matchId: string, targetOutcome?: string, notes?: string): Promise<boolean> => {
    try {
      const response = await fetch("/api/users/saved-matches", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ match_id: matchId, target_outcome: targetOutcome, notes }),
      });
      if (response.ok) {
        const newMatch = await response.json();
        setSavedMatches((previous) => [...previous.filter((match) => match.match_id !== matchId), newMatch]);
        analytics.track("saved_match_toggled", { match_id: matchId, action: "saved" });
        return true;
      }
    } catch {
      // Fall through to a failed mutation result.
    }
    return false;
  };

  const removeSavedMatch = async (matchId: string): Promise<boolean> => {
    try {
      const response = await fetch(`/api/users/saved-matches/${encodeURIComponent(matchId)}`, {
        method: "DELETE",
      });
      if (response.ok) {
        setSavedMatches((previous) => previous.filter((match) => match.match_id !== matchId && match.id !== matchId));
        analytics.track("saved_match_toggled", { match_id: matchId, action: "removed" });
        return true;
      }
    } catch {
      // Fall through to a failed mutation result.
    }
    return false;
  };

  const isMatchSaved = (matchId: string): boolean =>
    savedMatches.some((match) => match.match_id?.toLowerCase() === matchId?.toLowerCase());

  const updatePreferences = async (newPrefs: Partial<UserPreferences>): Promise<boolean> => {
    try {
      const merged = { ...preferences, ...newPrefs };
      const response = await fetch("/api/users/preferences", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(merged),
      });
      if (response.ok) {
        const data = await response.json();
        setPreferences({
          odds_format: data.odds_format || merged.odds_format || "DECIMAL",
          timezone: data.timezone || merged.timezone || "Africa/Lagos",
          default_league: data.default_league || merged.default_league || "EPL",
        });
        analytics.track("preferences_updated", { odds_format: data.odds_format, timezone: data.timezone });
        return true;
      }
    } catch {
      // Fall through to a failed mutation result.
    }
    return false;
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        isAuthenticated: !!user,
        isLoading,
        favorites,
        savedMatches,
        preferences,
        login,
        register,
        startGoogleSignIn,
        logout,
        toggleFavorite,
        isFavorite,
        saveMatch,
        removeSavedMatch,
        isMatchSaved,
        updatePreferences,
        refreshState: loadUserData,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
