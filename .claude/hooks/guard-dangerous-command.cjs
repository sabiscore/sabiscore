'use strict';

let input = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', chunk => { input += chunk; });
process.stdin.on('end', () => {
  try {
    const event = JSON.parse(input || '{}');
    const command = String(event?.tool_input?.command ?? '');

    const rules = [
      // rm with recursive+force flags, either order, combined (-rf/-fr) or split (-r -f/-f -r), short or long form
      /(^|[;&|\n\r])\s*rm\s+(?:-\w*r\w*f\w*|-\w*f\w*r\w*|-r\s+-f|-f\s+-r|--recursive\s+(?:-f|--force)|--force\s+(?:-r|--recursive))\b/i,
      /(^|[;&|\n\r])\s*sudo(?:\s|$)/i,
      /\b(?:DROP\s+TABLE|DELETE\s+FROM|TRUNCATE\s+TABLE)\b/i,
      /\bcurl\b[^\n\r]*\|\s*(?:bash|sh|zsh)\b/i,
      /\bwget\b[^\n\r]*\|\s*(?:bash|sh|zsh)\b/i,
      /\bnpx\s+--yes\b[^\n\r]*\|\s*(?:bash|sh|zsh)\b/i,
      /\bgit\s+push\b[^\n\r]*(?:--force|-f|--force-with-lease)\b/i
    ];

    const matched = rules.find(rule => rule.test(command));
    if (!matched) process.exit(0);

    process.stdout.write(JSON.stringify({
      hookSpecificOutput: {
        hookEventName: 'PreToolUse',
        permissionDecision: 'deny',
        permissionDecisionReason: 'SCAR guard blocked a destructive or unsafe shell command.'
      }
    }));
  } catch (error) {
    console.error(`[SCAR GUARD] Invalid hook input: ${error.message}`);
    process.exit(1);
  }
});
