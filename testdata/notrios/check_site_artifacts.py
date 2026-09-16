"""Development-only checks over the small 7b site fixtures, not a corpus scanner."""
import json, hashlib, sys
from pathlib import Path
root=Path(sys.argv[1])
fixture=Path(__file__).resolve().parent/'schema28/publication-loose'
e=json.loads((fixture/'expected.json').read_text()); results={}
for backend in ('bluge','pagefind'):
    site=root/backend; public=site/'public'
    rows=[json.loads(l) for l in (site/'server/search-source.jsonl').read_text().splitlines()]
    assert len(rows)==3
    assert sorted(t for r in rows for t in r['tags'])==['café','published','published','published','research notes','東京']
    assert all('préface' not in r['tags'] for r in rows)
    assert {r['url'] for r in rows}=={'/notes/public/cafe-field-notes.html','/notes/public/cafe-field-notes-2.html','/notes/public/研究/child-東京.html'}
    for r in rows: assert (public/r['url'].lstrip('/')).is_file()
    paths=[p for p in public.rglob('*') if p.is_file()]+[site/'server/search-source.jsonl']
    for p in paths:
        raw=p.read_bytes()
        for sentinel in e['forbidden_in_archive']:
            assert sentinel.encode() not in raw,(backend,str(p),sentinel)
        assert str(root).encode() not in raw,(backend,str(p),'local path')
        if p.suffix=='.html' or p.name=='search-source.jsonl':
            for key in ('commit_sha256','selection_manifest_sha256'): assert e[key].encode() not in raw
    receipt=json.loads((public/'movenotes/notrios-receipt.json').read_text())
    assert receipt==json.loads((root/'vault/.movenotes/notrios-receipt.json').read_text())
    assert (public/'pagefind').exists()==(backend=='pagefind')
    resources={hashlib.sha256(p.read_bytes()).hexdigest() for p in (public/'vault-assets').rglob('*') if p.is_file()}
    assert resources=={v['sha256'] for v in e['resources'].values()}
    results[backend]={'scanned_files':len(paths),'html_pages':len(list(public.rglob('*.html'))),'notes':3,'explicit_tags':4,'memberships':6,'resources':3,'receipt':receipt,'sentinels':len(e['forbidden_in_archive'])}
assert {p.relative_to(fixture/'archive').as_posix():{'size_bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in (fixture/'archive').rglob('*') if p.is_file()}==e['archive_files']
(root/'artifact-results.json').write_text(json.dumps(results,indent=2))
print(json.dumps(results,indent=2))
