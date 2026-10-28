#!/usr/bin/env python3
"""Capture exact saved note bytes through the running Obsidian app."""
import argparse
import base64
import json
import subprocess
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--vault', required=True, help='Obsidian vault name')
parser.add_argument('--path', required=True, help='Exact vault-relative note path')
parser.add_argument('--output', required=True, type=Path)
args = parser.parse_args()
code = f'''(async () => {{
  const file = app.vault.getAbstractFileByPath({json.dumps(args.path)});
  if (!file || !('extension' in file) || file.extension !== 'md') throw Error('Target note not found');
  const bytes = new TextEncoder().encode(await app.vault.read(file));
  return 'ENO_BASE64:' + btoa(Array.from(bytes, b => String.fromCharCode(b)).join(''));
}})()'''
result = subprocess.run(['obsidian', 'vault=' + args.vault, 'eval', 'code=' + code], capture_output=True, text=True)
prefix = '=> ENO_BASE64:'
if result.returncode or not result.stdout.startswith(prefix):
    raise SystemExit((result.stdout + result.stderr).strip() or 'Obsidian failed to read the note')
args.output.write_bytes(base64.b64decode(result.stdout[len(prefix):].strip(), validate=True))
print('Captured:', args.output)
