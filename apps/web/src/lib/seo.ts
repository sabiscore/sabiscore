/**
 * Programmatic Schema.org Structured Data Generators for SabiScore SEO.
 * Strictly adheres to Google Search Central specifications for SportsEvent,
 * SportsTeam, and BreadcrumbList.
 */

export interface SportsEventData {
  matchId: string;
  homeTeam: string;
  awayTeam: string;
  startDate: string;
  league: string;
  venue?: string | null;
  homeWinProb?: number;
  drawProb?: number;
  awayWinProb?: number;
  url?: string;
}

export function generateSportsEventJsonLd(data: SportsEventData) {
  const siteUrl = process.env.NEXT_PUBLIC_SITE_URL || "https://sabiscore.com";
  const eventUrl = data.url || `${siteUrl}/match/${encodeURIComponent(data.matchId)}?league=${encodeURIComponent(data.league)}`;

  return {
    "@context": "https://schema.org",
    "@type": "SportsEvent",
    "name": `${data.homeTeam} vs ${data.awayTeam}`,
    "startDate": data.startDate,
    "url": eventUrl,
    "sport": "Soccer",
    "competitor": [
      {
        "@type": "SportsTeam",
        "name": data.homeTeam,
      },
      {
        "@type": "SportsTeam",
        "name": data.awayTeam,
      },
    ],
    "location": {
      "@type": "Place",
      "name": data.venue || `${data.homeTeam} Stadium`,
    },
    "organizer": {
      "@type": "Organization",
      "name": data.league,
      "url": `${siteUrl}/intelligence?league=${encodeURIComponent(data.league)}`,
    },
    "description": `Evidence-backed quantitative football match intelligence and probability forecast for ${data.homeTeam} vs ${data.awayTeam} in the ${data.league}.`,
  };
}

export interface SportsTeamData {
  teamName: string;
  slug: string;
  league: string;
  logoUrl?: string;
}

export function generateSportsTeamJsonLd(data: SportsTeamData) {
  const siteUrl = process.env.NEXT_PUBLIC_SITE_URL || "https://sabiscore.com";
  return {
    "@context": "https://schema.org",
    "@type": "SportsTeam",
    "name": data.teamName,
    "sport": "Soccer",
    "url": `${siteUrl}/team/${encodeURIComponent(data.slug)}`,
    "memberOf": {
      "@type": "SportsOrganization",
      "name": data.league,
    },
    "image": data.logoUrl || `${siteUrl}/icon.svg`,
  };
}

export interface BreadcrumbItem {
  name: string;
  url: string;
}

export function generateBreadcrumbJsonLd(items: BreadcrumbItem[]) {
  const siteUrl = process.env.NEXT_PUBLIC_SITE_URL || "https://sabiscore.com";
  return {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    "itemListElement": items.map((item, index) => ({
      "@type": "ListItem",
      "position": index + 1,
      "name": item.name,
      "item": item.url.startsWith("http") ? item.url : `${siteUrl}${item.url.startsWith("/") ? "" : "/"}${item.url}`,
    })),
  };
}
