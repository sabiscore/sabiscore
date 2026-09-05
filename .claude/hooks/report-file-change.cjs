'use strict';

// PostToolUse only surfaces context to Claude via JSON hookSpecificOutput.additionalContext.
// Stderr on exit 0 goes to the debug log only and is never shown to Claude or the user.
let input = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', chunk => { input += chunk; });
process.stdin.on('end', () => {
  try {
    const event = JSON.parse(input || '{}');
    const tool = String(event?.tool_name ?? 'unknown');
    const filePath = String(event?.tool_input?.file_path ?? event?.tool_input?.path ?? 'unknown');
    process.stdout.write(JSON.stringify({
      hookSpecificOutput: {
        hookEventName: 'PostToolUse',
        additionalContext: `File modified: ${filePath} (${tool}) — run \`make validate\` before considering this change complete.`
      }
    }));
    process.exit(0);
  } catch (error) {
    // No valid input to report on; stay silent rather than emit an unparsable hint.
    process.exit(0);
  }
});
