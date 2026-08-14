import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { LeagueOffseasonNotice } from "./LeagueOffseasonNotice";

describe("LeagueOffseasonNotice", () => {
  it("describes the estimated UCL opener without an exact countdown", () => {
    render(
      <LeagueOffseasonNotice
        leagueName="UEFA Champions League"
        leagueCode="UCL"
        nextSeasonStart="2026-09-15"
        nextSeasonStartEstimated
      />,
    );

    expect(screen.getByText(/Season currently expected around/i)).toBeInTheDocument();
    expect(screen.getByText(/Date not yet confirmed by the provider/i)).toBeInTheDocument();
    expect(screen.queryByText(/days away/i)).not.toBeInTheDocument();
    expect(screen.getByText("UCL")).toBeInTheDocument();
  });

  it("uses confirmed copy for a provider-published opener", () => {
    render(
      <LeagueOffseasonNotice
        leagueName="Bundesliga"
        nextSeasonStart="2026-08-28"
        nextSeasonStartEstimated={false}
      />,
    );

    expect(screen.getByText(/Next season kicks off/i)).toBeInTheDocument();
    expect(screen.queryByText(/not yet confirmed/i)).not.toBeInTheDocument();
  });
});
