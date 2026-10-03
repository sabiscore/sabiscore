import { describe, expect, it } from "vitest";

import { bookmakerLabel } from "./bookmaker";

describe("bookmakerLabel", () => {
  it("names a known provider key and title-cases an unknown one", () => {
    expect(bookmakerLabel("pinnacle")).toBe("Pinnacle");
    expect(bookmakerLabel("betfair_ex_eu")).toBe("Betfair Exchange");
    expect(bookmakerLabel("some_new_book")).toBe("Some New Book");
  });
});
