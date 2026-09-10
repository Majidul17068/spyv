"""Small independently calculable corpus checks for the experiment driver."""
import json
import subprocess

import pytest
import yaml

from spyv.bench import corrective_study as study


def test_empty_denominator_and_path_sensitivity():
    assert study.describe({})['yield'] is None
    assert study.stratum('scripts/agent.py', False) == 'scaffolding'
    assert study.stratum('scripts/agent.py', False, False) == 'other'
    assert study.stratum('src/agent.py', True, False) == 'scaffolding'


def test_pinned_corpus_counts_and_dirty_rejection(tmp_path, monkeypatch):
    root = tmp_path/'tiny'
    root.mkdir()
    (root/'agent.py').write_text('SYSTEM_PROMPT="hello"\nAgent(instructions=SYSTEM_PROMPT)\nAgent(instructions=build())\n')
    (root/'broken.py').write_text('def :')
    (root/'alias.py').symlink_to('agent.py')
    subprocess.run(['git','init','-q',str(root)], check=True)
    study.git(root, 'add', '.')
    study.git(root, '-c', 'user.name=Majidul17068', '-c', 'user.email=majidulislam17068@gmail.com',
              '-c', 'commit.gpgsign=false', 'commit', '-qm', 'Synthetic measurement fixture')
    manifest = tmp_path/'manifest.yaml'
    manifest.write_text(yaml.safe_dump({'repos':[{'name':'tiny','framework':'generic',
        'sha':study.git(root,'rev-parse','HEAD').decode().strip()}]}))
    monkeypatch.setattr(study, 'DRAWS', 100)
    study.run(tmp_path, tmp_path/'out', manifest)
    result = json.loads((tmp_path/'out/results.json').read_text())
    scoped = result['summary']['all']['scoped/all/all']
    assert (scoped['static'],scoped['partial'],scoped['opaque']) == (2,0,1)
    assert result['summary']['all']['literal/use/all']['yield'] == 0
    assert result['summary']['all']['scoped/use/all']['yield'] == .5
    assert result['repositories'][0]['parsed_python'] == 1
    assert {x['reason'] for x in result['repositories'][0]['exclusions']} == {'symlink','SyntaxError'}
    (root/'agent.py').write_text('changed = True')
    with pytest.raises(RuntimeError, match='Tracked Python modifications'):
        study.run(tmp_path, tmp_path/'dirty-out', manifest)
