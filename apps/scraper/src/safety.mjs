export function parseRobotsAllow(robotsText, path, userAgent = "*") {
  const lines = robotsText.split(/\r?\n/);
  let active = false;
  const disallows = [];
  const allows = [];

  for (const rawLine of lines) {
    const line = rawLine.split("#")[0].trim();
    if (!line) continue;
    const [keyRaw, ...valueParts] = line.split(":");
    const key = keyRaw.trim().toLowerCase();
    const value = valueParts.join(":").trim();

    if (key === "user-agent") {
      const agent = value.toLowerCase();
      active = agent === "*" || userAgent.toLowerCase().includes(agent);
      continue;
    }
    if (!active) continue;
    if (key === "disallow" && value) disallows.push(value);
    if (key === "allow" && value) allows.push(value);
  }

  const longestAllow = allows.filter((rule) => path.startsWith(rule)).sort((a, b) => b.length - a.length)[0];
  const longestDisallow = disallows.filter((rule) => path.startsWith(rule)).sort((a, b) => b.length - a.length)[0];
  if (!longestDisallow) return true;
  if (!longestAllow) return false;
  return longestAllow.length >= longestDisallow.length;
}
