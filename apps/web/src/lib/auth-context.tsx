"use client";

import React, { createContext, useContext, useEffect, useState, useCallback } from "react";
import { analytics } from "@/lib/analytics";

export interface UserProfile {
  id: string;
  email: string;
  username?: string;
  full_name?: string;
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

interface AuthContextType {
  user: UserProfile | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  favorites: UserFavorite[];
  savedMatches: SavedMatch[];
  preferences: UserPreferences | null;
  login: (email: string, password: string) => Promise<{ success: boolean; error?: string }>;
  register: (username: string, email: string, password: string) => Promise<{ success: boolean; error?: string }>;
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

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<UserProfile | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [favorites, setFavorites] = useState<UserFavorite[]>([]);
  const [savedMatches, setSavedMatches] = useState<SavedMatch[]>([]);
  const [preferences, setPreferences] = useState<UserPreferences | null>({
    odds_format: "DECIMAL",
    timezone: "Africa/Lagos",
    default_league: "EPL",
  });

  const loadUserData = useCallback(async () => {
    try {
      // 1. Fetch current profile
      const meRes = await fetch("/api/auth/me", { cache: "no-store" });
      if (meRes.ok) {
        const userData = await meRes.json();
        setUser(userData);
      } else {
        setUser(null);
      }
    } catch {
      setUser(null);
    }

    try {
      // 2. Fetch favorites (supports anonymous session as well)
      const favRes = await fetch("/api/users/favorites", { cache: "no-store" });
      if (favRes.ok) {
        const favData = await favRes.json();
        setFavorites(Array.isArray(favData) ? favData : favData.favorites || []);
      }
    } catch {
      // Ignore transient errors
    }

    try {
      // 3. Fetch saved matches (supports anonymous session as well)
      const smRes = await fetch("/api/users/saved-matches", { cache: "no-store" });
      if (smRes.ok) {
        const smData = await smRes.json();
        setSavedMatches(Array.isArray(smData) ? smData : smData.saved_matches || []);
      }
    } catch {
      // Ignore transient errors
    }

    try {
      // 4. Fetch preferences
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
      // Ignore transient errors
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadUserData();
  }, [loadUserData]);

  const login = async (email: string, password: string): Promise<{ success: boolean; error?: string }> => {
    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        return { success: false, error: err.detail || "Invalid email or password." };
      }

      await loadUserData();
      analytics.track("dashboard_viewed", { source: "login" });
      return { success: true };
    } catch {
      return { success: false, error: "Network error during login." };
    }
  };

  const register = async (
    username: string,
    email: string,
    password: string
  ): Promise<{ success: boolean; error?: string }> => {
    try {
      const res = await fetch("/api/auth/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, email, password }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        return { success: false, error: err.detail || "Registration failed." };
      }

      // Automatically log in with credentials
      return await login(email, password);
    } catch {
      return { success: false, error: "Network error during registration." };
    }
  };

  const logout = async () => {
    try {
      await fetch("/api/auth/logout", { method: "POST" });
    } catch {
      // Ignore error on logout
    }
    setUser(null);
    await loadUserData();
  };

  const toggleFavorite = async (entityType: string, entityId: string): Promise<boolean> => {
    const existing = favorites.find(
      (f) => f.entity_id?.toLowerCase() === entityId.toLowerCase()
    );

    if (existing) {
      // Remove
      try {
        const delRes = await fetch(`/api/users/favorites/${encodeURIComponent(existing.id || entityId)}`, {
          method: "DELETE",
        });
        if (delRes.ok) {
          setFavorites((prev) => prev.filter((f) => f.id !== existing.id && f.entity_id !== entityId));
          analytics.track("favorite_toggled", { entity_type: entityType, entity_id: entityId, action: "removed" });
          return true;
        }
      } catch {}
      return false;
    } else {
      // Add
      try {
        const addRes = await fetch("/api/users/favorites", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ entity_type: entityType, entity_id: entityId }),
        });
        if (addRes.ok) {
          const newFav = await addRes.json();
          setFavorites((prev) => [...prev, newFav]);
          analytics.track("favorite_toggled", { entity_type: entityType, entity_id: entityId, action: "added" });
          return true;
        }
      } catch {}
      return false;
    }
  };

  const isFavorite = (entityId: string): boolean => {
    return favorites.some((f) => f.entity_id?.toLowerCase() === entityId?.toLowerCase());
  };

  const saveMatch = async (matchId: string, targetOutcome?: string, notes?: string): Promise<boolean> => {
    try {
      const res = await fetch("/api/users/saved-matches", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ match_id: matchId, target_outcome: targetOutcome, notes }),
      });
      if (res.ok) {
        const newMatch = await res.json();
        setSavedMatches((prev) => [...prev.filter((m) => m.match_id !== matchId), newMatch]);
        analytics.track("saved_match_toggled", { match_id: matchId, action: "saved" });
        return true;
      }
    } catch {}
    return false;
  };

  const removeSavedMatch = async (matchId: string): Promise<boolean> => {
    try {
      const res = await fetch(`/api/users/saved-matches/${encodeURIComponent(matchId)}`, {
        method: "DELETE",
      });
      if (res.ok) {
        setSavedMatches((prev) => prev.filter((m) => m.match_id !== matchId && m.id !== matchId));
        analytics.track("saved_match_toggled", { match_id: matchId, action: "removed" });
        return true;
      }
    } catch {}
    return false;
  };

  const isMatchSaved = (matchId: string): boolean => {
    return savedMatches.some((m) => m.match_id?.toLowerCase() === matchId?.toLowerCase());
  };

  const updatePreferences = async (newPrefs: Partial<UserPreferences>): Promise<boolean> => {
    try {
      const merged = { ...preferences, ...newPrefs };
      const res = await fetch("/api/users/preferences", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(merged),
      });
      if (res.ok) {
        const data = await res.json();
        setPreferences({
          odds_format: data.odds_format || merged.odds_format || "DECIMAL",
          timezone: data.timezone || merged.timezone || "Africa/Lagos",
          default_league: data.default_league || merged.default_league || "EPL",
        });
        analytics.track("preferences_updated", { odds_format: data.odds_format, timezone: data.timezone });
        return true;
      }
    } catch {}
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
