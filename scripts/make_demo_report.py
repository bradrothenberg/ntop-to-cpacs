"""Build the nTop report from verified measurements and saved native images."""
import argparse
import html
import json
from pathlib import Path
import shutil
from string import Template

ROOT = Path(__file__).resolve().parents[1]


def make(run):
    result = json.loads((run / 'verification.json').read_text())
    assert result['passed']
    errors = [value['max_decoded_point_error_m'] for value in result['cpacs'].values()]
    wing = [row for row in result['section_bounds_comparison'] if row['axis'] == 'y']
    most = max(wing, key=lambda row: row['max_bounds_coordinate_change_mm'])
    images = []
    for label, angle in [('baseline', 2), ('changed', 4)]:
        if (run / f'{label}-native.png').is_file():
            images.append(
                f'<div class="model"><img src="{label}-native.png" '
                f'alt="Native nTop GBI aircraft at {angle} degrees tip twist">'
                f'<div class="model-caption"><div><span class="mono">{label}</span>'
                f'<strong>{angle}&deg; tip twist</strong></div>'
                f'<a href="GBI-{label}.ntop" download>Download .ntop</a></div></div>'
            )
    if not images:
        images.append('<p class="src">Native images were not captured for this run. Inspect the saved notebooks and measured section plots.</p>')
    reopen_row = ''
    if (run / 'reopen-receipt.json').is_file():
        receipt = json.loads((run / 'reopen-receipt.json').read_text())
        assert receipt['tip_twist']['value'] == 4
        assert receipt['airframe_state']['buildState'] == 'e_OK'
        reopen_row = '<tr><td>Saved notebook</td><td>The API reopens the final file at 4&deg; with build state <code>e_OK</code>.</td><td><span class="pill p-info">Pass</span></td></tr>'
    template = Template((ROOT / 'templates/report.html').read_text(encoding='utf-8'))
    repair_section = ''
    if (run / 'twist-law-audit.json').is_file():
        repair = json.loads((run / 'twist-law-audit.json').read_text())
        native = json.loads((run / 'native-transition-verification.json').read_text())
        assert repair['passed'] and native['passed']
        repair_section = f'''<section aria-labelledby="repair-heading">
  <h2 id="repair-heading"><span class="num">02 / TWIST TRANSITION REPAIR</span>A smooth transition beside the center body</h2>
  <p>The previous 4&deg; model added {abs(repair['root_added_displacement_at_gate_end_mm']):.3f} mm of vertical placement across the existing narrow root band. This produced the visible crease.</p>
  <p>The updated construction retains the original 2&deg; shape in that band. A smooth gate distributes the additional twist through the wing/body transition.</p>
  <figure><div class="figlbl">Twist repair / Scalar construction comparison</div><img class="plot" src="twist-transition.png" alt="Previous and repaired twist laws, showing the removed abrupt root placement">
  <figcaption class="figure-note">The added-twist gate has three continuous derivatives. It starts at construction Y = 0.3055 m and reaches the linear law at 1 m. Native coordinate maps compose with these construction coordinates.</figcaption></figure>
  <div class="call"><span class="lbl">Measured checks</span><p>Native checks use {native['point_count']} fixed points per model. The protected-band field difference is {native['root_field_error_m']:.3g} m. The outer-station field difference at Y = 1.5 m and 2 m is {native['outer_field_error_m']:.3g} m.</p><p>These values compare scalar fields, not surface distances. The repair addresses the reported root crease. It does not establish global surface fairness or aerodynamic performance.</p></div>
  <div class="files"><a href="twist-law-audit.json">Twist-law evidence</a><a href="native-transition-verification.json">Native field checks</a><a href="previous-native.png">Previous 4&deg; native view</a></div>
</section>'''
    text = template.substitute(
        profile_count=result['cpacs']['baseline']['profiles'],
        bounds_change=f"{most['max_bounds_coordinate_change_mm']:.3f}",
        station=f"{most['station_m']:.3f}",
        point_error=f'{max(errors):.3g}',
        images=''.join(images), reopen_row=reopen_row, run_name=html.escape(run.name),
        repair_section=repair_section,
    )
    assets = run / 'assets'
    assets.mkdir(exist_ok=True)
    for name in ['ntop-docs.css', 'report.css', 'nTop_icon_black.png', 'nTop_icon_white.png']:
        shutil.copy2(ROOT / 'assets' / name, assets / name)
    (run / 'demo.html').write_text(text, encoding='utf-8')
    print(run / 'demo.html')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('run', type=Path)
    make(parser.parse_args().run.resolve())
