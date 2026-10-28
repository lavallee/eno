#!/usr/bin/env python3
"""Queue a note proposal through the running Obsidian app."""
import argparse
import base64
import json
import subprocess
from pathlib import Path
from uuid import uuid4


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vault', required=True, help='Obsidian vault name')
    parser.add_argument('--path', required=True, help='Exact vault-relative target path')
    parser.add_argument('--base', required=True, type=Path, help='File containing the exact text read')
    parser.add_argument('--proposed', required=True, type=Path, help='File containing the replacement text')
    args = parser.parse_args()
    base = args.base.read_bytes().decode('utf-8')
    proposed = args.proposed.read_bytes().decode('utf-8')
    if base == proposed:
        parser.error('proposal has no changes')
    payload = json.dumps({'path': args.path, 'base': base, 'proposed': proposed}, ensure_ascii=False)
    encoded = base64.b64encode(payload.encode()).decode('ascii')
    name = 'Eno Proposals/proposal-' + uuid4().hex + '.md'
    # All content is encoded before embedding it in JavaScript. Obsidian owns
    # vault access, including on macOS where another process may lack access.
    code = f'''(async () => {{
      const bytes = Uint8Array.from(atob({json.dumps(encoded)}), c => c.charCodeAt(0));
      const raw = new TextDecoder().decode(bytes);
      const p = JSON.parse(raw);
      const file = app.vault.getAbstractFileByPath(p.path);
      if (!file || !file.path.endsWith('.md') || !('extension' in file)) throw Error('Target note not found');
      if (await app.vault.read(file) !== p.base) throw Error('Target changed; read it again before proposing');
      if (!app.vault.getAbstractFileByPath('Eno Proposals')) await app.vault.createFolder('Eno Proposals');
      await app.vault.create({json.dumps(name)}, raw);
      return 'Queued: ' + {json.dumps(name)};
    }})()'''
    result = subprocess.run(['obsidian', 'vault=' + args.vault, 'eval', 'code=' + code], capture_output=True, text=True)
    if result.returncode or not result.stdout.startswith('=> Queued:'):
        raise SystemExit((result.stdout + result.stderr).strip() or 'Obsidian failed to queue the proposal')
    print(result.stdout.strip().removeprefix('=> '))


if __name__ == '__main__':
    main()
