/**
 * Observation Handler - PostToolUse
 *
 * Extracted from save-hook.ts - sends tool usage to worker for storage.
 */

import type { EventHandler, NormalizedHookInput, HookResult } from '../types.js';
import { ensureWorkerRunning, workerHttpRequest } from '../../shared/worker-utils.js';
import { getProjectName } from '../../utils/project-name.js';
import { logger } from '../../utils/logger.js';
import { HOOK_EXIT_CODES } from '../../shared/hook-constants.js';
import { isProjectExcluded } from '../../utils/project-filter.js';
import { SettingsDefaultsManager } from '../../shared/SettingsDefaultsManager.js';
import { USER_SETTINGS_PATH } from '../../shared/paths.js';
import { normalizePlatformSource } from '../../shared/platform-source.js';

export const observationHandler: EventHandler = {
  async execute(input: NormalizedHookInput): Promise<HookResult> {
    // Ensure worker is running before any other logic
    const workerReady = await ensureWorkerRunning();
    if (!workerReady) {
      // Worker not available - skip observation gracefully
      return { continue: true, suppressOutput: true, exitCode: HOOK_EXIT_CODES.SUCCESS };
    }

    const { sessionId, cwd, toolName, toolInput, toolResponse } = input;
    const platformSource = normalizePlatformSource(input.platform);

    if (!toolName) {
      // No tool name provided - skip observation gracefully
      return { continue: true, suppressOutput: true, exitCode: HOOK_EXIT_CODES.SUCCESS };
    }

    // Review gate responses are user input, not tool output — reclassify as user prompts
    // to prevent AI observation model history poisoning (non-XML responses cascade)
    if (toolName === 'review_gate_chat') {
      let userText = '';
      let parsed: unknown = toolResponse;
      if (typeof parsed === 'string') {
        const raw = parsed;
        try { parsed = JSON.parse(raw) as unknown; } catch { userText = raw; }
      }
      if (!userText && parsed && typeof parsed === 'object') {
        const resp = parsed as Record<string, unknown>;
        const content = Array.isArray(resp.content) ? resp.content : [];
        const textParts = content
          .filter((c: Record<string, unknown>) => c.type === 'text' && typeof c.text === 'string')
          .map((c: Record<string, unknown>) => c.text as string);
        userText = textParts.length > 0 ? textParts.join('\n') : JSON.stringify(parsed);
      }
      if (!userText) userText = String(toolResponse ?? '');
      try {
        await workerHttpRequest('/api/sessions/init', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            contentSessionId: sessionId,
            project: getProjectName(cwd),
            prompt: userText
          })
        });
        logger.debug('HOOK', 'Review gate reclassified as user prompt', { contentSessionId: sessionId });
      } catch { /* graceful failure — review gate storage is best-effort */ }
      return { continue: true, suppressOutput: true, exitCode: HOOK_EXIT_CODES.SUCCESS };
    }

    const toolStr = logger.formatTool(toolName, toolInput);

    logger.dataIn('HOOK', `PostToolUse: ${toolStr}`, {});

    // Validate required fields before sending to worker
    if (!cwd) {
      throw new Error(`Missing cwd in PostToolUse hook input for session ${sessionId}, tool ${toolName}`);
    }

    // Check if project is excluded from tracking
    const settings = SettingsDefaultsManager.loadFromFile(USER_SETTINGS_PATH);
    if (isProjectExcluded(cwd, settings.CLAUDE_MEM_EXCLUDED_PROJECTS)) {
      logger.debug('HOOK', 'Project excluded from tracking, skipping observation', { cwd, toolName });
      return { continue: true, suppressOutput: true };
    }

    // Send to worker - worker handles privacy check and database operations
    try {
      const response = await workerHttpRequest('/api/sessions/observations', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          contentSessionId: sessionId,
          platformSource,
          tool_name: toolName,
          tool_input: toolInput,
          tool_response: toolResponse,
          cwd
        })
      });

      if (!response.ok) {
        // Log but don't throw — observation storage failure should not block tool use
        logger.warn('HOOK', 'Observation storage failed, skipping', { status: response.status, toolName });
        return { continue: true, suppressOutput: true, exitCode: HOOK_EXIT_CODES.SUCCESS };
      }

      logger.debug('HOOK', 'Observation sent successfully', { toolName });
    } catch (error) {
      // Worker unreachable — skip observation gracefully
      logger.warn('HOOK', 'Observation fetch error, skipping', { error: error instanceof Error ? error.message : String(error) });
      return { continue: true, suppressOutput: true, exitCode: HOOK_EXIT_CODES.SUCCESS };
    }

    return { continue: true, suppressOutput: true };
  }
};
