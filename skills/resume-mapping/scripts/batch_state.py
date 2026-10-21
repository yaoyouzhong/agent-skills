"""Immutable, hash-bound batch stages and honest wall-clock accounting."""
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def file_hash(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def stamp():
    return {'utc': datetime.now(timezone.utc).isoformat(), 'monotonic_ns': time.monotonic_ns()}


def engines(*names):
    base = Path(__file__).parent
    return {name: file_hash(base/name) for name in ('batch_state.py', *names)}


class Task:
    def __init__(self, root, create=False):
        self.root = Path(root).resolve()
        self.path = self.root/'batch-state.json'
        if create:
            self.root.mkdir(parents=True, exist_ok=False)
            self.state = {'schema_version': 1, 'started': stamp(), 'cache': {}, 'events': []}
            self.save()
        else:
            self.state = read(self.path)

    def save(self):
        temporary = self.path.with_suffix('.next.json')
        write(temporary, self.state)
        temporary.replace(self.path)

    def event(self, kind, **extra):
        self.state['events'].append({'kind': kind, **stamp(), **extra})
        self.save()

    def mark(self, phase, state):
        if state not in ('start', 'stop'):
            raise ValueError('Agent interval state must be start or stop.')
        pending = self.state.get('agent_interval')
        if state == 'start':
            if pending:
                raise ValueError('Finish the active Agent interval first.')
            self.state['agent_interval'] = {'phase': phase, **stamp()}
            self.event('agent_start', phase=phase)
        else:
            if not pending or pending['phase'] != phase:
                raise ValueError('No matching active Agent interval.')
            self.event('agent_stop', phase=phase, seconds=(time.monotonic_ns()-pending['monotonic_ns'])/1e9)
            del self.state['agent_interval']
            self.save()

    def step(self, name, bindings, action):
        key = digest(bindings)
        entries = self.state['cache'].setdefault(name, {})
        entry = entries.get(key)
        if entry:
            receipt = Path(entry['receipt'])
            valid = receipt.is_file() and file_hash(receipt) == entry['sha256']
            saved = read(receipt) if valid else None
            valid = valid and saved['bindings'] == bindings and all(
                (receipt.parent/p).is_file() and file_hash(receipt.parent/p) == h
                for p, h in saved['files'].items())
            if valid:
                self.event('cache_hit', stage=name, key=key)
                return saved['result']
            self.event('cache_invalidated', stage=name, key=key)
        parent = self.root/'stages'/name
        parent.mkdir(parents=True, exist_ok=True)
        attempt = 1
        while (parent/f'{key[:20]}-{attempt}').exists():
            attempt += 1
        folder = parent/f'{key[:20]}-{attempt}'
        folder.mkdir()
        started = time.monotonic_ns()
        self.event('program_start', stage=name, key=key)
        try:
            result = action(folder)
            files = {p.relative_to(folder).as_posix(): file_hash(p) for p in sorted(folder.rglob('*')) if p.is_file()}
            receipt = folder/'stage-receipt.json'
            write(receipt, {'bindings': bindings, 'files': files, 'result': result})
            entries[key] = {'receipt': str(receipt), 'sha256': file_hash(receipt)}
            self.event('program_stop', stage=name, key=key, seconds=(time.monotonic_ns()-started)/1e9, status='completed')
            return result
        except Exception as error:
            self.event('program_stop', stage=name, key=key, seconds=(time.monotonic_ns()-started)/1e9,
                       status='failed', error=str(error))
            raise

    def timing(self):
        events = self.state['events']
        elapsed = (time.monotonic_ns()-self.state['started']['monotonic_ns'])/1e9
        program = sum(x['seconds'] for x in events if x['kind'] == 'program_stop')
        # Agent intervals include thinking, tool interaction and any idle time.
        # They are not model inference time. Program stages may overlap them.
        return {'wall_seconds': elapsed, 'program_stage_seconds': program,
                'agent_intervals': [x for x in events if x['kind'] == 'agent_stop'],
                'cache_hits': sum(x['kind'] == 'cache_hit' for x in events),
                'events': events, 'scope': 'Observed task wall clock; Agent intervals are not model inference time.'}
