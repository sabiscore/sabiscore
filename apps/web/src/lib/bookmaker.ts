// The Odds API sends bookmaker keys ("pinnacle", "williamhill"); consumers see names.
const NAMES: Record<string, string> = {
  pinnacle: "Pinnacle",
  bet365: "Bet365",
  betfair_ex_eu: "Betfair Exchange",
  betfair_ex_uk: "Betfair Exchange",
  williamhill: "William Hill",
  unibet_eu: "Unibet",
  unibet_uk: "Unibet",
  onexbet: "1xBet",
  marathonbet: "Marathonbet",
  betsson: "Betsson",
  sport888: "888sport",
  paddypower: "Paddy Power",
  skybet: "Sky Bet",
  coral: "Coral",
  ladbrokes_uk: "Ladbrokes",
  betvictor: "BetVictor",
  matchbook: "Matchbook",
};

export function bookmakerLabel(key: string): string {
  const k = key.trim().toLowerCase();
  return NAMES[k] ?? k.replaceAll("_", " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
