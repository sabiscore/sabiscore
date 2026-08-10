/* eslint-disable jsx-a11y/aria-proptypes */
"use client";

import { useEffect, useMemo, useRef, useState, useId, useCallback } from "react";
import { TeamDisplay } from "./team-display";
import { Clock, Star, Search } from "lucide-react";

interface TeamAutocompleteProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: readonly string[];
  league?: string;
  placeholder?: string;
  disabled?: boolean;
  showRecent?: boolean;
  maxRecent?: number;
}

const RECENT_TEAMS_KEY = 'sabiscore:recent-teams';
const MAX_RECENT_DEFAULT = 5;

/**
 * Fuzzy match score - higher is better
 */
function fuzzyScore(query: string, target: string): number {
  const q = query.toLowerCase();
  const t = target.toLowerCase();
  
  // Exact match
  if (t === q) return 1000;
  
  // Starts with query
  if (t.startsWith(q)) return 500 + (q.length / t.length) * 100;
  
  // Contains query as substring
  const index = t.indexOf(q);
  if (index !== -1) return 300 - index + (q.length / t.length) * 50;
  
  // Fuzzy character matching
  let score = 0;
  let queryIdx = 0;
  let consecutiveBonus = 0;
  
  for (let i = 0; i < t.length && queryIdx < q.length; i++) {
    if (t[i] === q[queryIdx]) {
      score += 10 + consecutiveBonus;
      consecutiveBonus += 5; // Bonus for consecutive matches
      queryIdx++;
    } else {
      consecutiveBonus = 0;
    }
  }
  
  // All query characters found
  if (queryIdx === q.length) {
    return score + (q.length / t.length) * 20;
  }
  
  // Word boundary matches (e.g., "MU" matches "Manchester United")
  const words = t.split(/\s+/);
  const initials = words.map(w => w[0]).join('');
  if (initials.includes(q)) {
    return 200 + q.length * 10;
  }
  
  return 0;
}

/**
 * Get recent teams from localStorage
 */
function getRecentTeams(): string[] {
  if (typeof window === 'undefined') return [];
  try {
    const stored = localStorage.getItem(RECENT_TEAMS_KEY);
    return stored ? JSON.parse(stored) : [];
  } catch {
    return [];
  }
}

/**
 * Save team to recent selections
 */
function saveRecentTeam(team: string, maxRecent: number): void {
  if (typeof window === 'undefined' || !team.trim()) return;
  try {
    const recent = getRecentTeams().filter(t => t !== team);
    recent.unshift(team);
    localStorage.setItem(RECENT_TEAMS_KEY, JSON.stringify(recent.slice(0, maxRecent)));
  } catch {
    // Ignore storage errors
  }
}

/**
 * Enhanced combobox with fuzzy search and recent selections.
 */
export function TeamAutocomplete({
  label,
  value,
  onChange,
  options,
  league,
  placeholder,
  disabled,
  showRecent = true,
  maxRecent = MAX_RECENT_DEFAULT
}: TeamAutocompleteProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const [internalValue, setInternalValue] = useState(value);
  const [isOpen, setIsOpen] = useState(false);
  const [highlightedIndex, setHighlightedIndex] = useState(-1);
  const [recentTeams, setRecentTeams] = useState<string[]>([]);
  const uid = useId();

  // Load recent teams on mount
  useEffect(() => {
    setRecentTeams(getRecentTeams());
  }, []);

  useEffect(() => {
    setInternalValue(value);
  }, [value]);

  // Ensure menu closes when component becomes disabled
  useEffect(() => {
    if (disabled) {
      setIsOpen(false);
      setHighlightedIndex(-1);
    }
  }, [disabled]);

  // Scroll highlighted option into view
  useEffect(() => {
    if (highlightedIndex >= 0 && listRef.current) {
      const highlightedItem = listRef.current.children[highlightedIndex] as HTMLElement;
      if (highlightedItem) {
        highlightedItem.scrollIntoView({ block: 'nearest' });
      }
    }
  }, [highlightedIndex]);

  const filteredOptions = useMemo(() => {
    const query = internalValue.trim().toLowerCase();
    
    // No query: show recent teams first (if enabled), then all options
    if (!query) {
      if (showRecent && recentTeams.length > 0) {
        const validRecent = recentTeams.filter(t => options.includes(t));
        const nonRecent = options.filter(t => !validRecent.includes(t));
        return {
          recent: validRecent,
          suggestions: nonRecent.slice(0, 10), // Limit initial suggestions
          hasMore: nonRecent.length > 10
        };
      }
      return {
        recent: [],
        suggestions: [...options].slice(0, 15),
        hasMore: options.length > 15
      };
    }

    // Score and sort by fuzzy match
    const scored = options
      .map(team => ({ team, score: fuzzyScore(query, team) }))
      .filter(item => item.score > 0)
      .sort((a, b) => b.score - a.score)
      .map(item => item.team);

    return {
      recent: [],
      suggestions: scored.slice(0, 20),
      hasMore: scored.length > 20
    };
  }, [internalValue, options, recentTeams, showRecent]);

  const allDisplayedOptions = useMemo(() => {
    return [...filteredOptions.recent, ...filteredOptions.suggestions];
  }, [filteredOptions]);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (!containerRef.current) {
        return;
      }

      if (!containerRef.current.contains(event.target as Node)) {
        setIsOpen(false);
        setHighlightedIndex(-1);
      }
    }

    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const handleSelect = useCallback((team: string) => {
    setInternalValue(team);
    onChange(team);
    setIsOpen(false);
    setHighlightedIndex(-1);
    
    // Save to recent teams
    saveRecentTeam(team, maxRecent);
    setRecentTeams(getRecentTeams());
    
    requestAnimationFrame(() => {
      inputRef.current?.focus();
    });
  }, [onChange, maxRecent]);

  const handleInputChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const nextValue = event.target.value;
    setInternalValue(nextValue);
    onChange(nextValue);
    if (!isOpen) {
      setIsOpen(true);
    }
    setHighlightedIndex(-1);
  };

  const handleInputFocus = () => {
    if (!disabled) {
      setIsOpen(true);
    }
  };

  const handleKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (disabled) return;

    if (!isOpen && ["ArrowDown", "ArrowUp"].includes(event.key)) {
      event.preventDefault();
      setIsOpen(true);
      // When opening via arrows, set an initial highlight for better UX
      setHighlightedIndex(event.key === "ArrowDown" ? 0 : Math.max(0, allDisplayedOptions.length - 1));
      return;
    }

    if (event.key === "ArrowDown") {
      event.preventDefault();
      setHighlightedIndex((current) =>
        current < 0 ? 0 : current + 1 >= allDisplayedOptions.length ? 0 : current + 1
      );
    }

    if (event.key === "ArrowUp") {
      event.preventDefault();
      setHighlightedIndex((current) =>
        current < 0 ? Math.max(0, allDisplayedOptions.length - 1) : current <= 0 ? allDisplayedOptions.length - 1 : current - 1
      );
    }

    if (event.key === "Enter") {
      if (highlightedIndex >= 0 && highlightedIndex < allDisplayedOptions.length) {
        event.preventDefault();
        handleSelect(allDisplayedOptions[highlightedIndex]);
      } else {
        setIsOpen(false);
      }
    }

    if (event.key === "Escape") {
      setIsOpen(false);
      setHighlightedIndex(-1);
    }
    
    if (event.key === "Tab") {
      setIsOpen(false);
      setHighlightedIndex(-1);
    }
  };

  let currentIndex = 0;

  return (
    <div ref={containerRef} className="space-y-2">
      <label className="text-sm font-medium text-slate-300" htmlFor={`team-combobox-${uid}`}>{label}</label>
      <div className="relative">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
          <input
            ref={inputRef}
            type="text"
            id={`team-combobox-${uid}`}
            value={internalValue}
            onChange={handleInputChange}
            onFocus={handleInputFocus}
            onKeyDown={handleKeyDown}
            placeholder={placeholder}
            disabled={disabled}
            autoComplete="off"
            role="combobox"
            aria-autocomplete="list"
            aria-expanded={isOpen}
            aria-controls={`team-listbox-${uid}`}
            aria-activedescendant={
              highlightedIndex >= 0 ? `team-option-${uid}-${highlightedIndex}` : undefined
            }
            className="min-h-11 w-full pl-10 pr-4 py-3 bg-slate-800/50 border border-slate-700 rounded-lg text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition-all disabled:opacity-50 disabled:cursor-not-allowed"
          />
        </div>
        {isOpen && allDisplayedOptions.length > 0 && (
          <div
            ref={listRef as unknown as React.RefObject<HTMLDivElement>}
            id={`team-listbox-${uid}`}
            role="listbox"
            aria-label={`${label} options`}
            className="absolute z-20 mt-1 w-full max-h-72 overflow-auto rounded-lg border border-slate-700 bg-slate-900/95 shadow-xl backdrop-blur-sm"
          >
            {/* Recent Teams Section */}
            {filteredOptions.recent.length > 0 && (
              <>
                <div className="px-3 py-1.5 text-xs font-semibold text-slate-400 uppercase tracking-wide flex items-center gap-2 bg-slate-900/50 border-b border-slate-700/50">
                  <Clock className="w-3 h-3" />
                  Recent
                </div>
                {filteredOptions.recent.map((team) => {
                  const index = currentIndex++;
                  return (
                    <div
                      key={`recent-${team}`}
                      id={`team-option-${uid}-${index}`}
                      role="option"
                      aria-selected={highlightedIndex === index}
                      tabIndex={-1}
                      title={team}
                      className={`flex min-h-11 cursor-pointer items-center gap-2 px-4 py-2.5 text-sm transition-colors ${
                        highlightedIndex === index
                          ? "bg-indigo-600 text-white"
                          : "text-slate-200 hover:bg-slate-800"
                      }`}
                      onMouseDown={(event) => event.preventDefault()}
                      onClick={() => handleSelect(team)}
                      onMouseEnter={() => setHighlightedIndex(index)}
                    >
                      <Star className={`w-3 h-3 ${highlightedIndex === index ? 'text-yellow-300' : 'text-yellow-500'}`} />
                      <TeamDisplay 
                        teamName={team} 
                        size="sm" 
                        variant="compact"
                        league={league}
                        showLeaguePill={Boolean(league)}
                        className={highlightedIndex === index ? "text-white" : ""}
                      />
                    </div>
                  );
                })}
              </>
            )}
            
            {/* Suggestions Section */}
            {filteredOptions.suggestions.length > 0 && (
              <>
                {filteredOptions.recent.length > 0 && (
                  <div className="px-3 py-1.5 text-xs font-semibold text-slate-400 uppercase tracking-wide flex items-center gap-2 bg-slate-900/50 border-b border-slate-700/50">
                    <Search className="w-3 h-3" />
                    All Teams
                  </div>
                )}
                {filteredOptions.suggestions.map((team) => {
                  const index = currentIndex++;
                  return (
                    <div
                      key={team}
                      id={`team-option-${uid}-${index}`}
                      role="option"
                      aria-selected={highlightedIndex === index}
                      tabIndex={-1}
                      title={team}
                      className={`flex min-h-11 cursor-pointer items-center px-4 py-2.5 text-sm transition-colors ${
                        highlightedIndex === index
                          ? "bg-indigo-600 text-white"
                          : "text-slate-200 hover:bg-slate-800"
                      }`}
                      onMouseDown={(event) => event.preventDefault()}
                      onClick={() => handleSelect(team)}
                      onMouseEnter={() => setHighlightedIndex(index)}
                    >
                      <TeamDisplay 
                        teamName={team} 
                        size="sm" 
                        variant="compact"
                        league={league}
                        showLeaguePill={Boolean(league)}
                        className={highlightedIndex === index ? "text-white" : ""}
                      />
                    </div>
                  );
                })}
              </>
            )}
            
            {/* More results indicator */}
            {filteredOptions.hasMore && (
              <div role="presentation" className="px-4 py-2 text-xs text-slate-500 text-center border-t border-slate-700/50">
                Type to see more results...
              </div>
            )}
          </div>
        )}

        {isOpen && allDisplayedOptions.length === 0 && (
          <div className="absolute z-20 mt-1 w-full rounded-lg border border-slate-700 bg-slate-900/95 px-4 py-3 text-sm text-slate-400 shadow-lg">
            No teams found. Keep typing to use a custom name.
          </div>
        )}
      </div>
    </div>
  );
}
