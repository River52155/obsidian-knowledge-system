"""Offline generation maintenance. Service shared lease excludes pruning."""
import argparse,fcntl,json,os,re,shutil,socket
from contextlib import contextmanager
from pathlib import Path

NAME=re.compile(r'generation-[A-Za-z0-9_-]+\Z')

@contextmanager
def _lock(data_dir,exclusive):
    root=Path(data_dir).resolve();root.mkdir(parents=True,exist_ok=True)
    fd=os.open(root/'.maintenance.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:
        try:fcntl.flock(fd,(fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)|fcntl.LOCK_NB)
        except BlockingIOError:raise ValueError('索引正在使用或维护，请先停止服务再清理。') from None
        yield
    finally:os.close(fd)

def service_lock(data_dir):return _lock(data_dir,False)

def plan_prune(data_dir,*,keep_previous=2):
    root=Path(data_dir).resolve();directory=root/'generations'
    if type(keep_previous) is not int or keep_previous<2:raise ValueError('至少保留最近两个非活动版本。')
    def valid(name):return isinstance(name,str) and bool(NAME.fullmatch(name))
    try:
        if directory.is_symlink() or not directory.is_dir() or not (root/'baseline.sqlite3').is_file():raise ValueError()
        pointer=root/'active-index.json';pins_file=root/'pinned-generations.json'
        if pointer.is_symlink() or pins_file.is_symlink():raise ValueError()
        active=json.loads(pointer.read_text())['generation']
        pins=json.loads(pins_file.read_text()) if pins_file.exists() else dict(schema_version=1,generations=[])
        if not valid(active) or set(pins)!={'schema_version','generations'} or pins['schema_version']!=1 or not isinstance(pins['generations'],list) or not all(valid(n) for n in pins['generations']):raise ValueError()
        complete=[];skipped=[]
        for p in directory.iterdir():
            if p.is_symlink() or not p.is_dir() or not valid(p.name) or any(not (p/n).is_file() or (p/n).is_symlink() for n in ['baseline.sqlite3','embedding-index.npz','snapshot.json']):skipped.append(p.name)
            else:complete.append(p)
        if active not in {p.name for p in complete}:raise ValueError()
        recent=sorted((p for p in complete if p.name!=active),key=lambda p:(p.stat().st_mtime_ns,p.name),reverse=True)[:keep_previous]
        keep={active,*pins['generations'],*(p.name for p in recent)};candidates=sorted(p.name for p in complete if p.name not in keep)
        size=sum(f.stat().st_size for p in complete if p.name in candidates for f in p.rglob('*') if f.is_file() and not f.is_symlink())
        return dict(active_generation=active,keep=sorted(keep),candidates=candidates,skipped=sorted(skipped),estimated_bytes=size)
    except (OSError,ValueError,TypeError,KeyError):raise ValueError('版本目录、活动指针或保留清单无效，未清理。') from None

def apply_prune(data_dir,*,keep_previous=2):
    root=Path(data_dir).resolve()
    # The installed pre-upgrade service predates shared maintenance locks.
    if root==Path(__file__).resolve().parent/'data':
        with socket.socket() as sock:
            if sock.connect_ex(('127.0.0.1',8767))==0:raise ValueError('请先停止8767服务再应用清理。')
    with _lock(root,True):
        plan=plan_prune(root,keep_previous=keep_previous);removed=[];failed=[]
        for name in plan['candidates']:
            path=root/'generations'/name
            if path.is_symlink():failed.append(name);break
            try:shutil.rmtree(path);removed.append(name)
            except OSError:failed.append(name);break
        return dict(plan,removed=removed,failed=failed,complete=not failed)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=['prune']);p.add_argument('--data-dir',type=Path,default=Path(__file__).parent/'data');p.add_argument('--apply',action='store_true');a=p.parse_args()
    try:print(json.dumps(apply_prune(a.data_dir) if a.apply else plan_prune(a.data_dir),ensure_ascii=False,indent=2))
    except ValueError as e:p.exit(1,str(e)+'\n')
