"""Compare native fields around the repaired wing/body transition."""
import argparse
import json
from pathlib import Path
import numpy as np
from native_probe import probe, sha
from scalar_graph import Graph


def verify(baseline, old, candidate, out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    ys = [.1, .219456, .24, .27, .3, .3055, .4, .65, .8, 1., 1.5, 2.]
    points = np.array([[x, sign*y, z] for x in [3.5, 4.5, 5.5, 6.5]
                       for y in ys for z in [-.1, .17, .35] for sign in [-1, 1]])
    values = []
    sources = [('baseline', baseline), ('previous', old), ('repaired', candidate)]
    receipts = {}
    for label, source in sources:
        folder = out / label
        if (folder/'receipt.json').is_file():
            saved = json.loads((folder/'receipt.json').read_text())
            assert saved['source_sha256'] == sha(source)
            data = np.load(folder/'measurements.npz')
            assert np.array_equal(data['points'], points)
            assert list(data['fields']) == ['placement', 'airframe']
            field = data['values']
        else:
            field = probe(source, points, {'placement': 51177, 'airframe': 35023}, folder)
        assert np.isfinite(field).all()
        scalar = np.asarray(Graph(source).eval([51177], points))[0]
        error = float(np.max(abs(field[0] - scalar)))
        assert error < 1e-10, error
        receipts[label] = json.loads((folder/'receipt.json').read_text())
        receipts[label]['placement_scalar_error_m'] = error
        values.append(field)
    a, b, c = values
    protected = abs(points[:, 1]) <= .3055
    # The gate ends at construction Y=1 m. Other native coordinate maps
    # compose with it, so world-space Y=1 m need not be outside that gate.
    # Check the retained outer-wing stations separately from the scalar law.
    outer = abs(points[:, 1]) >= 1.5
    root_error = float(np.max(abs(c[:, protected] - a[:, protected])))
    outer_error = float(np.max(abs(c[:, outer] - b[:, outer])))
    assert root_error < 1e-10 and outer_error < 1e-10
    result = dict(passed=True, point_count=len(points), receipts=receipts,
                  root_field_error_m=root_error, outer_field_error_m=outer_error,
                  outer_world_stations_m=[1.5, 2.0],
                  transition_world_y1_field_change_m=float(np.max(abs(c[:, abs(points[:,1])==1.] - b[:, abs(points[:,1])==1.]))),
                  scope='Native placement and final-airframe scalar field checks at fixed points. These are field values, not surface distances.')
    (out/'native-transition-verification.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    for name in ['baseline', 'old', 'candidate', 'out']:
        p.add_argument(name, type=Path)
    verify(**vars(p.parse_args()))
