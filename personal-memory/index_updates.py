"""Build immutable index generations; publish only a validated, stable pair."""
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import threading

from memory_search import ROOTS, SENSITIVE_NAME, build, files_under, metadata


def now():
    return datetime.now().astimezone().isoformat(timespec='seconds')


def active_db(base_db):
    """Resolve the service's published version for read-only command-line queries."""
    base_db = Path(base_db).resolve()
    pointer = base_db.parent / 'active-index.json'
    if not pointer.exists():
        return base_db
    saved = json.loads(pointer.read_text())
    directory = base_db.parent / 'generations'
    folder = directory / saved['generation']
    if folder.parent != directory or folder.is_symlink():
        raise ValueError('已发布索引位置无效。')
    db = folder / 'baseline.sqlite3'
    if not db.is_file():
        raise ValueError('已发布索引缺失。')
    return db


def snapshot(vault):
    """Only allowed roots. Hash text; inventory attachments without opening them."""
    if not vault.is_dir():
        raise ValueError('资料目录暂不可用，保留旧索引。')
    result = {}
    for root in ROOTS:
        for p in files_under(vault / root):
            relative = p.relative_to(vault)
            stat = p.stat()
            value = [stat.st_size, stat.st_mtime_ns]
            if p.suffix.lower() in {'.md', '.txt'} and not any(SENSITIVE_NAME.search(s) for s in relative.parts):
                value = hashlib.sha256(p.read_bytes()).hexdigest()
                after = p.stat()
                if (stat.st_size, stat.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    raise ValueError('扫描期间文件变化，稍后重试。')
            result[relative.as_posix()] = value
    return result


def atomic_json(path, value):
    fd, name = tempfile.mkstemp(prefix='.pointer-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if Path(name).exists():
            Path(name).unlink()


class IndexUpdates:
    def __init__(self, base_db, interval=60, embed=None, validate=None):
        from semantic_search import build_embeddings, validate_index
        self.base_db = Path(base_db).resolve()
        self.vault = Path(metadata(self.base_db)['vault'])
        self.directory = self.base_db.parent / 'generations'
        self.directory.mkdir(exist_ok=True, mode=0o700)
        self.pointer = self.base_db.parent / 'active-index.json'
        self.embed = embed or (lambda db, dest: build_embeddings(db, dest, write_report=False, reuse_from=self.current_db().parent, progress=lambda p:self.set_state(progress=p)))
        self.validate = validate or validate_index
        self.interval = interval
        self._db = self.base_db
        self._snapshot = None
        self.lock = threading.Lock()
        self.busy = threading.Lock()
        self.wake = threading.Event()
        self.stopped = threading.Event()
        self.state = dict(state='idle', phase='idle', message='等待首次检查。', last_checked=None, last_updated=None, last_success_at=None, last_failure=None, active_error=None, progress=None, pending_changes=dict(added=0,removed=0,modified=0))
        if self.pointer.exists():
            try:
                saved = json.loads(self.pointer.read_text())
                folder = self.directory / saved['generation']
                if folder.parent != self.directory or folder.is_symlink():
                    raise ValueError('Invalid generation')
                db = folder / 'baseline.sqlite3'
                self.validate(db)
                self._snapshot = json.loads((folder / 'snapshot.json').read_text())
                self._db = db
                self.state['last_updated'] = saved['updated_at']
            except Exception:
                self.state.update(state='error', message='上次版本无法加载，暂用初始索引，等待重新检查。')

    def current_db(self):
        with self.lock:
            return self._db

    def status(self):
        with self.lock:
            return dict(self.state, enabled=True, interval_seconds=self.interval,
                        generation=self._db.parent.name, running=self.busy.locked(), retained_generations=sum(p.is_dir() and not p.is_symlink() for p in self.directory.iterdir()))

    def set_state(self, **values):
        with self.lock:
            self.state.update(values)

    def _needs_rebuild(self, snapshot_value):
        from research_catalog import catalog_schema_version, SCHEMA_VERSION
        from memory_search import connect
        if snapshot_value != self._snapshot:return True
        try:
            with connect(self.current_db()) as con:
                if catalog_schema_version(con)!=SCHEMA_VERSION:return True
            result=self.validate(self.current_db())
            return bool(isinstance(result,dict) and result.get('upgrade_required'))
        except (ValueError,OSError,sqlite3.Error):return True

    def refresh(self):
        if not self.busy.acquire(blocking=False):
            return
        stage = None
        try:
            self.set_state(state='checking', phase='checking', check_requested=False, message='正在检查约定目录的变化。')
            before = snapshot(self.vault)
            self.set_state(last_checked=now())
            if before == self._snapshot and not self._needs_rebuild(before):
                self.set_state(state='current', phase='idle', active_error=None, error_type=None, last_success_at=now(), pending_changes=dict(added=0,removed=0,modified=0), progress=None, message='已检查，资料没有变化。')
                return
            old = self._snapshot
            changes = None if old is None else dict(added=len(before.keys()-old.keys()),
                removed=len(old.keys()-before.keys()), modified=sum(before[k] != old[k] for k in before.keys() & old.keys()))
            self.set_state(state='building', phase='building_text', message='正在本机准备新索引，搜索继续使用上一版。', changes=changes, pending_changes=changes or dict(added=0,removed=0,modified=0), progress=None)
            stage = Path(tempfile.mkdtemp(prefix='generation-', dir=self.directory))
            db = stage / 'baseline.sqlite3'
            build(self.vault, db)
            inv = metadata(db, 'inventory')
            if any(row['status'] in {'read_failed', 'changed_during_read'} for row in inv):
                from retrieval_service import allowed_path
                failed=[r['path'] for r in inv if r['status'] in {'read_failed','changed_during_read'} and allowed_path(r['path'])]
                self.set_state(active_error=dict(code='READ_FAILED',stage='building_text',paths=failed[:10],total_paths=len(failed)))
                raise ValueError('部分文字读取失败，本次未切换索引。')
            self.set_state(phase='embedding')
            self.embed(db, stage / 'embedding-index.npz')
            self.set_state(phase='validating')
            self.validate(db)
            after = snapshot(self.vault)
            if before != after:
                raise ValueError('生成期间资料变化，本次未切换，下一轮再试。')
            atomic_json(stage / 'snapshot.json', after)
            updated = now()
            self.set_state(phase='publishing')
            with self.lock:
                atomic_json(self.pointer, dict(generation=stage.name, updated_at=updated))
                self._db, self._snapshot = db, after
                self.state.update(state='current', phase='idle', active_error=None, error_type=None, last_success_at=updated, pending_changes=dict(added=0,removed=0,modified=0), message='新索引已就绪，文字与向量已一起切换。', last_updated=updated)
            stage = None
        except Exception as error:
            # Do not surface file contents, exception bodies, or credentials in status.
            prior=self.status();failure=prior.get('active_error')
            if not failure or failure['stage']!=prior['phase']:failure=dict(code='UPDATE_FAILED',stage=prior['phase'],paths=[],total_paths=0)
            self.set_state(state='error', phase='error', active_error=failure, last_failure=dict(time=now(),code=failure['code'],stage=failure['stage']), error_type=type(error).__name__, message='本次更新未完成，保留上一版；下一轮自动重试，也可点击检查更新。')
        finally:
            if stage is not None:
                shutil.rmtree(stage)
            self.busy.release()

    def trigger(self):
        self.set_state(check_requested=True)
        self.wake.set()
        return self.status()

    def start(self):
        def loop():
            while not self.stopped.is_set():
                self.wake.clear()
                self.refresh()
                self.wake.wait(self.interval)
        self.thread = threading.Thread(target=loop, daemon=True, name='index-updates')
        self.thread.start()

    def stop(self):
        self.stopped.set()
        self.wake.set()
