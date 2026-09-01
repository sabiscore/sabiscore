import { ImageResponse } from "next/og";
import { NextRequest } from "next/server";

export const runtime = "edge";

function formatFixtureTitle(value: string): string {
  return decodeURIComponent(value || "match")
    .replace(/[-_]/g, " ")
    .replace(/\bvs\b/gi, "vs")
    .replace(/\b\w/g, (character) => character.toUpperCase())
    .slice(0, 96);
}

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const fixtureTitle = formatFixtureTitle(id);

  return new ImageResponse(
    (
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          width: "100%",
          height: "100%",
          backgroundColor: "#07110f",
          color: "#f8fafc",
          padding: "56px 64px",
          justifyContent: "space-between",
          fontFamily: "sans-serif",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "14px" }}>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                width: "48px",
                height: "48px",
                borderRadius: "8px",
                backgroundColor: "#10b981",
                color: "#07110f",
                fontWeight: 900,
                fontSize: "26px",
              }}
            >
              S
            </div>
            <div style={{ display: "flex", flexDirection: "column" }}>
              <span style={{ fontSize: "26px", fontWeight: 800 }}>SabiScore</span>
              <span style={{ fontSize: "13px", color: "#6ee7b7", textTransform: "uppercase" }}>
                Evidence-backed football intelligence
              </span>
            </div>
          </div>
          <span
            style={{
              padding: "8px 16px",
              borderRadius: "8px",
              backgroundColor: "rgba(56, 189, 248, 0.12)",
              border: "1px solid rgba(56, 189, 248, 0.35)",
              color: "#7dd3fc",
              fontSize: "14px",
              fontWeight: 700,
            }}
          >
            Match analysis
          </span>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
          <div style={{ fontSize: "52px", fontWeight: 900, color: "#ffffff", maxWidth: "1040px" }}>
            {fixtureTitle}
          </div>
          <div style={{ display: "flex", maxWidth: "920px", fontSize: "24px", lineHeight: 1.45, color: "#cbd5e1" }}>
            Open the match page for the current evidence state, model availability, and analytical verdict.
          </div>
        </div>

        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            borderTop: "1px solid rgba(255, 255, 255, 0.12)",
            paddingTop: "22px",
            fontSize: "15px",
            color: "#94a3b8",
          }}
        >
          <span>Missing or conflicting evidence remains unavailable.</span>
          <span>Research and decision support</span>
        </div>
      </div>
    ),
    {
      width: 1200,
      height: 630,
    }
  );
}