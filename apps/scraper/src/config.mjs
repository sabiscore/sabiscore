import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { sourceRegistry } from "./registry.mjs";

export const workspaceRoot = resolve(fileURLToPath(new URL("../../..", import.meta.url)));
export const rawDir = resolve(workspaceRoot, "data/raw/node-scraper");
export const processedDir = resolve(workspaceRoot, "data/processed/node-scraper");
export const manifestDir = resolve(workspaceRoot, "data/manifests/node-scraper");

export const scraperUserAgent =
  process.env.SCRAPER_USER_AGENT ??
  "SabiScoreDataResearch/1.0 (+https://sabiscore.local; contact: data@sabiscore.local)";

export const sourceAllowlist = sourceRegistry.sources;
export const sourceRegistryVersion = sourceRegistry.registryVersion;

export const defaultLeagues = sourceRegistry.competitions;
