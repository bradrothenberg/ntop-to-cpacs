"""Verify the public example without a local nTop installation."""
import argparse
import copy
import json
from pathlib import Path
import tempfile
import numpy as np
from cpacs_bridge import sha, SOURCE_SHA, NS, permitted_change, load_manifest
from verify_demo import decode_check, native_twist, contract_checks
from ntop_container import read, write
from scalar_graph import Graph

ROOT = Path(__file__).resolve().parents[1]


def verify(folder):
    folder = Path(folder).resolve()
    manifest = json.loads((folder/'package-manifest.json').read_text())
    for name, digest in manifest['files'].items():
        path = (folder/name).resolve()
        assert path.is_relative_to(folder) and sha(path) == digest, name
    assert sha(ROOT/'source/GBI-V38.ntop') == SOURCE_SHA
    results, recipes = {}, []
    for label, angle in [('baseline', 2), ('changed', 4)]:
        m = load_manifest(folder/f'{label}-sections.json')
        assert m['source_sha256'] == sha(folder/f'{label}-working.ntop')
        for row in m['sections']:
            assert sha(row['curves']) == row['curve_sha256']
        results[label] = decode_check(folder/f'{label}.xml', folder/f'{label}-sections.json')
        assert abs(native_twist(folder/f'GBI-{label}.ntop')-angle) < 1e-12
        chunks = []
        for filename in [f'{label}-working.ntop', f'GBI-{label}.ntop']:
            h, c = read(folder/filename)
            assert write(h, c) == (folder/filename).read_bytes()
            chunks.append({v.name: v.serialize() for v in c if v.name not in ['open', 'sections']})
        assert chunks[0] == chunks[1]
        recipe = json.loads((folder/f'{label}.recipe.json').read_text())
        control = next(n for n in recipe['body'] if n.get('name') == 'Tip twist')
        value = control['contents']['value']
        assert value['units'] == {'angle': 1}
        assert abs(np.rad2deg(value['val'])-angle) < 1e-12
        value['val'] = 0
        recipes.append(recipe)
        y = np.linspace(0, 2.75, 11001)
        points = np.c_[np.full_like(y, 6.8), y, np.zeros_like(y)]
        t = np.clip((y-.3055)/.6945, 0, 1)
        gate = t**4*(35+t*(-84+t*(70-20*t)))
        expected = np.deg2rad(2+(angle-2)*gate)*np.minimum(y/2.7432, 1)
        actual = Graph(folder/f'{label}-working.ntop').eval('Explicit source twist', points)
        assert np.max(abs(actual-expected)) < 1e-12
    assert recipes[0] == recipes[1]
    permitted_change(folder/'baseline.xml', folder/'request.xml')
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)
        for name in ['baseline.xml', 'request.xml']:
            (p/name).write_bytes((folder/name).read_bytes())
        checks = contract_checks(p)
    for name in ['baseline-api.json', 'apply-receipt.json', 'reopen-receipt.json']:
        receipt = json.loads((folder/name).read_text())
        assert receipt['airframe_state']['buildState'] == 'e_OK'
    proof = json.loads((folder/'repair-binding.json').read_text())
    assert proof['candidate_and_final_recipes_equal']
    assert proof['final_recipe_sha256'] == sha(folder/'changed.recipe.json')
    candidate = folder/'repair-evidence/repaired.recipe.json'
    assert sha(candidate) == proof['candidate_recipe_sha256']
    assert json.loads(candidate.read_text()) == json.loads((folder/'changed.recipe.json').read_text())
    for label in ['baseline', 'previous', 'repaired']:
        receipt = json.loads((folder/'repair-evidence'/f'{label}-receipt.json').read_text())
        assert receipt['source_sha256'] == sha(folder/'repair-evidence'/f'{label}.ntop')
    renders = json.loads((folder/'render-evidence.json').read_text())
    for label in ['baseline', 'changed']:
        assert renders[label]['source_sha256'] == sha(folder/f'{label}-working.ntop')
        assert renders[label]['image_sha256'] == sha(folder/f'{label}-native.png')
    assert renders['baseline']['camera'] == renders['changed']['camera']
    arrays = [np.load(folder/'repair-evidence'/f'{s}-measurements.npz')
              for s in ['baseline', 'previous', 'repaired']]
    points = arrays[0]['points']
    assert all(np.array_equal(a['points'], points) for a in arrays)
    root, outer = abs(points[:,1]) <= .3055, abs(points[:,1]) >= 1.5
    a,b,c = [v['values'] for v in arrays]
    assert np.isfinite([a,b,c]).all()
    assert np.max(abs(c[:,root]-a[:,root])) < 1e-10
    assert np.max(abs(c[:,outer]-b[:,outer])) < 1e-10
    print(json.dumps(dict(passed=True, files=len(manifest['files']),
                          cpacs=results, rejected=checks['rejected_edits']), indent=2))


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('folder', type=Path, nargs='?', default=ROOT/'examples/gbi')
    verify(p.parse_args().folder)
