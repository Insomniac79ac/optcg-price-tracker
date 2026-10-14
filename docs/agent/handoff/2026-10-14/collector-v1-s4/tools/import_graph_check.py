"""Read-only: does this PR change any collector runtime input? Same tool as the
delivery continuity check (scripts/collector_runtime_inputs.py).
usage: import_graph_check.py <installed collector component sha> <base> [head]"""
import datetime, json, subprocess, sys
sys.path.insert(0, '/workspaces/cp-cv1-s4/scripts')
import collector_runtime_inputs as tool
component, base = sys.argv[1], sys.argv[2]
head = sys.argv[3] if len(sys.argv) > 3 else 'HEAD'
git = lambda *a: subprocess.check_output(['git', *a], text=True, cwd='/workspaces/cp-cv1-s4').strip()
head = git('rev-parse', head)
files = git('diff', '--name-only', base, head).split()
out = {'observed_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
       'installed_component': component, 'base': git('rev-parse', base), 'head': head,
       'pr_files': files,
       'touches_models_or_settings': [f for f in files if f.startswith('services/api/app/models/')
                                      or f in ('services/api/app/settings.py', 'services/api/requirements.txt',
                                               'services/api/pyproject.toml')],
       'collectors': {}}
for name in tool.COLLECTORS:
    reached = tool.runtime_inputs(component, name) | tool.runtime_inputs(head, name)
    changed, basis = tool.changed_runtime_inputs(component, head, name)
    out['collectors'][name] = {
        'basis': basis,
        'changed_runtime_inputs_component_to_head': changed,
        'pr_files_in_import_set': [f for f in files if any(f == q or f.startswith(q + '/') for q in tool.full_paths(name)) and tool.counts(f, reached)],
        'import_set_size': len(reached),
        'accounts_modules_reached': [p for p in reached if p.startswith('services/api/app/accounts/')],
        'models_init_imported': 'services/api/app/models/__init__.py' in reached,
        'settings_imported': 'services/api/app/settings.py' in reached,
    }
print(json.dumps(out, indent=1))
