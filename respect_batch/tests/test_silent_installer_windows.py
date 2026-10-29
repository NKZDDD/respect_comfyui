"""Opt-in real NSIS handoff. Set BATCH_TEST_MAKENSIS to makensis.exe on Windows.

Uses a tiny windowless payload and removes registry/shortcut writes from a test
copy of the installer, so the installed Studio and its files are never touched.
"""
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest


@pytest.mark.skipif(sys.platform != "win32" or not os.environ.get("BATCH_TEST_MAKENSIS"),
                    reason="requires Windows and BATCH_TEST_MAKENSIS")
def test_silent_installer_waits_and_restarts_in_original_directory(tmp_path):
    root = Path(__file__).resolve().parents[1]
    compiler = Path(os.environ["WINDIR"]) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
    payload, installed = tmp_path / "payload", tmp_path / "原目录 & with spaces"
    payload.mkdir()
    installed.mkdir()
    source = tmp_path / "restart.cs"
    source.write_text('''using System; using System.IO;
class App { static void Main() { File.WriteAllText(Path.Combine(
AppDomain.CurrentDomain.BaseDirectory, "restarted.txt"),
Environment.GetEnvironmentVariable("STV_DATA_DIR") ?? "missing"); } }
''', encoding="utf-8")
    executable = payload / "RespectBatch-User.exe"
    subprocess.run([str(compiler), "/nologo", "/target:winexe", "/out:"+str(executable), str(source)],
                   check=True, capture_output=True)
    (installed / "RespectBatch-User.exe").write_bytes(b"old-locked-payload")
    (payload / "batch-build.json").write_text('{"new_build":true}', encoding="utf-8")
    (installed / "batch-build.json").write_text('{"old_build":true}', encoding="utf-8")
    (installed / "config.json").write_text('{"sentinel":true}', encoding="utf-8")
    (installed / "projects").mkdir()
    (installed / "projects/keep.txt").write_text("keep", encoding="utf-8")
    remove = tmp_path / "remove.nsh"
    remove.write_text('Delete "$INSTDIR\\RespectBatch-User.exe"', encoding="utf-8")
    # Leave update/PID/mutex/copy/restart logic intact. Do not touch real shell
    # integration or bootstrap WebView2: this stub needs no browser runtime.
    script = (root / "tools/batch-installer.nsi").read_text(encoding="utf-8")
    script = script.replace("Local\\Respect.Batch.User", "Local\\Respect.Batch.Test."+str(os.getpid()))
    script = "\n".join(line for line in script.splitlines() if not any(x in line for x in (
        "InstallDirRegKey", "WriteReg", "DeleteRegKey", "$SMPROGRAMS", "$DESKTOP")))
    # Fail the test with an exit code instead of a blocking dialog on errors.
    script = "\n".join('  SetErrorLevel 2' if line.lstrip().startswith("MessageBox ") else line
                       for line in script.splitlines())
    nsi, installer = tmp_path / "test.nsi", tmp_path / "update setup.exe"
    nsi.write_text(script, encoding="utf-8")
    subprocess.run([os.environ["BATCH_TEST_MAKENSIS"], "/V2", "/INPUTCHARSET", "UTF8",
                    "/DVERSION=2026.10.22.3", "/DPAYLOAD="+str(payload), "/DOUTPUT="+str(installer),
                    "/DREMOVE_LIST="+str(remove), "/DAPP_ICON="+str(root / "web/favicon.ico"), str(nsi)],
                   check=True, capture_output=True, timeout=60)
    parent = tmp_path / "parent.py"
    parent.write_text('''import ctypes, os, pathlib, subprocess, sys, time
folder, installer, marker, release = map(pathlib.Path, sys.argv[1:])
k=ctypes.WinDLL('kernel32', use_last_error=True)
k.CreateMutexW.argtypes=[ctypes.c_void_p,ctypes.c_bool,ctypes.c_wchar_p]
k.CreateMutexW.restype=ctypes.c_void_p
mutex=k.CreateMutexW(None,False,'Local\\\\Respect.Batch.Test.'+os.environ['TEST_OWNER_PID'])
k.CreateFileW.argtypes=[ctypes.c_wchar_p,ctypes.c_ulong,ctypes.c_ulong,ctypes.c_void_p,ctypes.c_ulong,ctypes.c_ulong,ctypes.c_void_p]
k.CreateFileW.restype=ctypes.c_void_p
handle=k.CreateFileW(str(folder/'RespectBatch-User.exe'),0x80000000,1,None,3,0,None)
assert handle not in (None,ctypes.c_void_p(-1).value)
cmd=subprocess.list2cmdline([str(installer),'/S',f'/BATCHUPDATE={os.getpid()}'])+' /D='+str(folder)
p=subprocess.Popen(cmd,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=0x08000000)
marker.write_text(str(p.pid))
deadline=time.monotonic()+20
while not release.exists() and time.monotonic()<deadline: time.sleep(.05)
# Windows closes the file and mutex handles only when this process exits.
''', encoding="utf-8")
    marker, signal = tmp_path / "started.txt", tmp_path / "exit-now"
    data_dir = str(tmp_path / "用户数据")
    env = dict(os.environ, TEST_OWNER_PID=str(os.getpid()), STV_DATA_DIR=data_dir)
    p = subprocess.Popen([sys.executable, str(parent), str(installed), str(installer), str(marker), str(signal)],
                         env=env, creationflags=subprocess.CREATE_NO_WINDOW)
    updater_pid = None
    try:
        deadline = time.monotonic()+15
        while not marker.exists() and time.monotonic()<deadline:
            time.sleep(.05)
        assert marker.exists(), "parent did not launch installer"
        updater_pid = int(marker.read_text())
        import psutil
        updater = psutil.Process(updater_pid)
        time.sleep(1)
        assert p.poll() is None and updater.is_running()
        assert (installed / "RespectBatch-User.exe").read_bytes() == b"old-locked-payload"
        assert not (installed / "restarted.txt").exists()
        signal.touch()
        assert p.wait(timeout=15) == 0
        assert updater.wait(timeout=30) == 0
        deadline = time.monotonic()+10
        while not (installed / "restarted.txt").exists() and time.monotonic()<deadline:
            time.sleep(.05)
        assert (installed / "RespectBatch-User.exe").read_bytes() == executable.read_bytes()
        assert (installed / "restarted.txt").read_text(encoding="utf-8-sig") == data_dir
        assert (installed / "batch-build.json").read_text() == '{"new_build":true}'
        assert (installed / "config.json").read_text() == '{"sentinel":true}'
        assert (installed / "projects/keep.txt").read_text() == "keep"
        # Even a manually chosen Studio directory must never be reused for batch.
        (installed / 'Respect-Studio.exe').write_bytes(b'studio-sentinel')
        command = subprocess.list2cmdline([str(installer), '/S']) + ' /D=' + str(installed)
        rejected = subprocess.run(command, capture_output=True, timeout=20,
                                  creationflags=subprocess.CREATE_NO_WINDOW)
        assert rejected.returncode == 2
        assert (installed / 'Respect-Studio.exe').read_bytes() == b'studio-sentinel'
        assert (installed / 'RespectBatch-User.exe').read_bytes() == executable.read_bytes()
    finally:
        if p.poll() is None:
            p.kill()
            p.wait()
        if updater_pid:
            import psutil
            try:
                psutil.Process(updater_pid).kill()
            except psutil.NoSuchProcess:
                pass
