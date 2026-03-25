import { execSync } from 'child_process';
import * as path from 'path';
import * as fs from 'fs';

const handler = async (event: any) => {
  const workspaceDir = event.context?.workspaceDir || 
    process.env.OPENCLAW_WORKSPACE_DIR || 
    '/Users/mac/.openclaw/workspace';
  
  const scriptPath = path.join(workspaceDir, 'scripts', 'save_last_conversation.py');
  
  if (!fs.existsSync(scriptPath)) return;
  
  try {
    execSync(`python3 "${scriptPath}"`, {
      timeout: 10000,
      stdio: 'ignore',
      env: { ...process.env, WORKSPACE_DIR: workspaceDir }
    });
  } catch (e) {
    // Silent fail — don't break message flow
  }
};

export default handler;
