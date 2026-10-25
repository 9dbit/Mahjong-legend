"""Compile the reviewed v085 presentation edits on the immutable v084 sources.

The JSON contains ordinary line edits, not executable Python. Source SHA-256s
are checked to prevent silently rebuilding against another contributor's code.
Outputs are separate JS assets; original v084 files and math remain untouched.
"""
from pathlib import Path
import argparse,hashlib,json
ROOT=Path(__file__).resolve().parents[1]
SPEC=Path(__file__).with_name('runtime_v085_edits.json')
def build(runtime_only=False):
    spec=json.loads(SPEC.read_text())
    for item in spec['files']:
        if runtime_only and not item['target'].startswith(('web/','mahjong_legend/')):
            continue
        source=ROOT/item['source'];target=ROOT/item['target']
        if not source.resolve().is_relative_to(ROOT) or not target.resolve().is_relative_to(ROOT):
            raise ValueError('Runtime paths must be within the repository')
        raw=source.read_bytes()
        if source==target and hashlib.sha256(raw).hexdigest()==item['target_sha256']:
            continue
        if hashlib.sha256(raw).hexdigest()!=item['source_sha256']:
            raise ValueError('Upstream changed, review v085 edits: '+item['source'])
        lines=raw.decode('utf-8').splitlines(keepends=True)
        for edit in reversed(item['edits']):
            start,stop=edit['start'],edit['stop']
            lines[start:stop]=edit['insert'].splitlines(keepends=True)
        output=''.join(lines).encode()
        if hashlib.sha256(output).hexdigest()!=item['target_sha256']:
            raise ValueError('Generated runtime integrity mismatch')
        target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(output)
        print('Compiled',item['target'],len(output),'bytes')
if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--runtime-only',action='store_true',help='Skip QA/test derivations in the production image')
    build(runtime_only=parser.parse_args().runtime_only)
