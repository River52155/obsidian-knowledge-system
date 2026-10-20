"""Manage the user's local launchd service without relying on a terminal session."""
import argparse
import json
import os
from pathlib import Path
import plistlib
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen

HERE = Path(__file__).resolve().parent
LABEL = 'com.river.personal-memory'
PLIST = Path.home() / 'Library/LaunchAgents' / (LABEL+'.plist')
DOMAIN = f'gui/{os.getuid()}'


def launch_config():
    # launchd cannot posix_spawn the symlink under Documents on this Mac.
    # Use its external target plus the explicitly pinned virtualenv package path.
    logs = Path.home() / 'Library/Logs/PersonalMemory'
    packages = HERE / '.venv/lib' / f'python{sys.version_info.major}.{sys.version_info.minor}' / 'site-packages'
    return dict(Label=LABEL, ProgramArguments=[str((HERE/'.venv/bin/python').resolve()), '-u',
        str(HERE/'memory_search.py'), 'serve', '--port', '8767'], WorkingDirectory=str(Path.home()),
        RunAtLoad=True, KeepAlive=True, ThrottleInterval=10,
        EnvironmentVariables={'PATH':'/usr/bin:/bin:/usr/sbin:/sbin','PYTHONUNBUFFERED':'1',
                              'PYTHONPATH':str(packages),'PYTHONNOUSERSITE':'1'},
        StandardOutPath=str(logs/'stdout.log'), StandardErrorPath=str(logs/'stderr.log'))


def probe(base='http://127.0.0.1:8767'):
    try:
        with urlopen(base+'/api/health', timeout=2) as response:
            data = json.load(response)
    except (URLError, TimeoutError, OSError):
        return None
    except (ValueError, TypeError):
        raise ValueError('该端口运行了其他程序，未接管。') from None
    if not isinstance(data, dict) or data.get('service_id') != 'river.personal-memory':
        raise ValueError('该端口运行了其他程序，未接管。')
    return data


def launchctl(*args, check=True):
    result = subprocess.run(['/bin/launchctl',*args],capture_output=True,text=True)
    if check and result.returncode:
        raise ValueError('系统服务操作未完成，请查看本机服务状态。')
    return result.returncode


def occupied():
    with socket.socket() as sock:
        return sock.connect_ex(('127.0.0.1',8767)) == 0


def install():
    if occupied() and not probe():
        raise ValueError('端口已被占用，未修改服务。')
    config = launch_config()
    if PLIST.is_symlink():
        raise ValueError('启动配置是符号链接，未覆盖。')
    PLIST.parent.mkdir(parents=True,exist_ok=True)
    if PLIST.exists() and plistlib.loads(PLIST.read_bytes()) != config:
        backup = HERE/'data/config-backups'
        backup.mkdir(parents=True,exist_ok=True,mode=0o700)
        (backup/(str(time.time_ns())+'-'+PLIST.name)).write_bytes(PLIST.read_bytes())
    logs = Path(config['StandardOutPath']).parent
    logs.mkdir(parents=True,exist_ok=True,mode=0o700)
    for name in ['stdout.log','stderr.log']:
        p=logs/name
        p.touch(mode=0o600,exist_ok=True)
        p.chmod(0o600)
    PLIST.write_bytes(plistlib.dumps(config))
    PLIST.chmod(0o600)
    launchctl('bootout',DOMAIN+'/'+LABEL,check=False)
    return start()


def start():
    if not PLIST.is_file():
        raise ValueError('尚未安装，请先运行 install。')
    loaded = launchctl('print',DOMAIN+'/'+LABEL,check=False)==0
    if not loaded:
        if occupied():
            raise ValueError('端口已有进程；请先核对并停止旧服务，未自动终止。')
        launchctl('bootstrap',DOMAIN,str(PLIST))
    else:
        launchctl('kickstart',DOMAIN+'/'+LABEL)
    deadline=time.monotonic()+35
    while time.monotonic()<deadline:
        data=probe()
        if data and data.get('ready'):
            return data
        time.sleep(.2)
    raise ValueError('服务尚未就绪，请检查 ~/Library/Logs/PersonalMemory 下的启动日志。')


def stop():
    launchctl('bootout',DOMAIN+'/'+LABEL,check=False)
    return dict(stopped=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['install','start','stop','status','uninstall'])
    args=parser.parse_args()
    try:
        if args.action=='install': result=install()
        elif args.action=='start': result=start()
        elif args.action=='stop': result=stop()
        elif args.action=='uninstall':
            result=stop()
            if PLIST.is_file():PLIST.unlink()
        else: result=probe() or dict(ready=False,installed=PLIST.is_file())
        print(json.dumps(result,ensure_ascii=False))
    except ValueError as error:
        print(str(error),file=sys.stderr)
        raise SystemExit(1)


if __name__=='__main__':main()
