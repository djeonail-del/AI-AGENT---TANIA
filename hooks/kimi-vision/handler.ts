import { execSync } from 'child_process';
import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';

const handler = async (event: any) => {
  // Only run on gateway startup
  if (event.type !== 'gateway' || event.action !== 'startup') return;

  // Wait a bit for gateway to finish writing models.json
  await new Promise(resolve => setTimeout(resolve, 10000));

  const modelsPath = path.join(os.homedir(), '.openclaw', 'agents', 'main', 'agent', 'models.json');

  if (!fs.existsSync(modelsPath)) return;

  try {
    const raw = fs.readFileSync(modelsPath, 'utf8');
    const data = JSON.parse(raw);
    let patched = false;

    const providers = data?.providers ?? {};
    for (const [pname, pdata] of Object.entries(providers) as any) {
      if (pname.toLowerCase().includes('ollama')) {
        for (const model of pdata?.models ?? []) {
          if (model?.id?.toLowerCase().includes('kimi')) {
            if (!model.input?.includes('image')) {
              model.input = ['text', 'image'];
              patched = true;
              console.log(`[kimi-vision] Patched ${model.id} → text+image`);
            }
          }
        }
      }
    }

    if (patched) {
      fs.writeFileSync(modelsPath, JSON.stringify(data, null, 2));
      console.log('[kimi-vision] models.json updated');
    }
  } catch (e) {
    // Silent fail
    console.error('[kimi-vision] Error:', e);
  }
};

export default handler;
