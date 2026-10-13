"""Package one verified run with relative paths and an explicit file list."""
import argparse
import json
from pathlib import Path, PureWindowsPath
import shutil
from cpacs_bridge import sha


def portable(value):
    if isinstance(value, dict):
        return {k: portable(v) for k, v in value.items() if k != 'original_path'}
    if isinstance(value, list):
        return [portable(v) for v in value]
    if isinstance(value, str) and PureWindowsPath(value).is_absolute():
        return PureWindowsPath(value).name
    return value


def package(run, out):
    run, out = Path(run).resolve(), Path(out).resolve()
    verification = json.loads((run/'verification.json').read_text())
    assert verification['passed']
    if out.exists():
        raise FileExistsError('Use a new package directory to preserve the earlier export.')
    out.mkdir(parents=True)
    exact = ['baseline.xml', 'request.xml', 'changed.xml',
             'baseline-working.ntop', 'changed-working.ntop',
             'GBI-baseline.ntop', 'GBI-changed.ntop',
             'baseline.recipe.json', 'changed.recipe.json',
             'baseline-native.png', 'changed-native.png', 'previous-native.png',
             'section-comparison.png', 'twist-transition.png', 'twist-law.npz',
             'demo.html']
    for name in exact:
        shutil.copy2(run/name, out/name)
    shutil.copytree(run/'assets', out/'assets')
    for name in ['verification.json', 'baseline-api.json', 'apply-receipt.json',
                 'reopen-receipt.json', 'preparation-receipt.json',
                 'twist-law-audit.json', 'native-transition-verification.json',
                 'render-evidence.json', 'repair-binding.json']:
        data = portable(json.loads((run/name).read_text()))
        (out/name).write_text(json.dumps(data, indent=2))
    (out/'curves').mkdir()
    for label in ['baseline', 'changed']:
        data = json.loads((run/f'{label}-sections.json').read_text())
        data['source'] = f'{label}-working.ntop'
        for i, row in enumerate(data['sections']):
            source = Path(row['curves'])
            dest = out/'curves'/f'{label}-{i:03d}.npz'
            assert sha(source) == row['curve_sha256']
            shutil.copy2(source, dest)
            row['curves'] = dest.relative_to(out).as_posix()
            row.pop('path', None)
        (out/f'{label}-sections.json').write_text(json.dumps(data, indent=2))
    # The repair evidence includes the exact measured notebook states and arrays.
    # Raw probe notebooks, console scripts, process IDs, and logs stay local.
    shutil.copytree(run/'repair-evidence', out/'repair-evidence')
    files = {p.relative_to(out).as_posix(): sha(p) for p in sorted(out.rglob('*')) if p.is_file()}
    (out/'package-manifest.json').write_text(json.dumps(dict(
        source_run=run.name, paths='Relative to this directory', files=files), indent=2))
    print(json.dumps({'directory': str(out), 'files': len(files),
                      'bytes': sum(p.stat().st_size for p in out.rglob('*') if p.is_file())}))


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('run', type=Path)
    p.add_argument('out', type=Path)
    package(**vars(p.parse_args()))
