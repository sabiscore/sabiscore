import { describe, it, expect } from "vitest";
import {
  generateSportsEventJsonLd,
  generateSportsTeamJsonLd,
  generateBreadcrumbJsonLd,
} from "./seo";

describe("Programmatic SEO & JSON-LD Structured Data", () => {
  it("generates valid SportsEvent Schema.org structured data", () => {
    const jsonLd = generateSportsEventJsonLd({
      matchId: "arsenal-vs-chelsea",
      homeTeam: "Arsenal",
      awayTeam: "Chelsea",
      startDate: "2026-09-01T15:00:00Z",
      league: "EPL",
    });

    expect(jsonLd["@context"]).toBe("https://schema.org");
    expect(jsonLd["@type"]).toBe("SportsEvent");
    expect(jsonLd.name).toBe("Arsenal vs Chelsea");
    expect(jsonLd.competitor).toHaveLength(2);
    expect(jsonLd.competitor[0].name).toBe("Arsenal");
    expect(jsonLd.competitor[1].name).toBe("Chelsea");
  });

  it("generates valid SportsTeam Schema.org structured data", () => {
    const jsonLd = generateSportsTeamJsonLd({
      teamName: "Liverpool FC",
      slug: "liverpool",
      league: "Premier League",
    });

    expect(jsonLd["@context"]).toBe("https://schema.org");
    expect(jsonLd["@type"]).toBe("SportsTeam");
    expect(jsonLd.name).toBe("Liverpool FC");
    expect(jsonLd.url).toContain("/team/liverpool");
  });

  it("generates valid BreadcrumbList Schema.org structured data", () => {
    const jsonLd = generateBreadcrumbJsonLd([
      { name: "Home", url: "/" },
      { name: "Matches", url: "/match" },
      { name: "Arsenal vs Chelsea", url: "/match/arsenal-vs-chelsea" },
    ]);

    expect(jsonLd["@context"]).toBe("https://schema.org");
    expect(jsonLd["@type"]).toBe("BreadcrumbList");
    expect(jsonLd.itemListElement).toHaveLength(3);
    expect(jsonLd.itemListElement[0].position).toBe(1);
    expect(jsonLd.itemListElement[0].name).toBe("Home");
  });
});
