"""Native I/O helper: CAS conflicts, symlink refusal, literal argv and deadlines."""

from pathlib import Path
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "work/native-rootfs/usr/libexec/vpn-controller-io"


def run(*args):
    return subprocess.run([str(HELPER), *map(str, args)], check=False).returncode


with tempfile.TemporaryDirectory(dir=ROOT / "work", prefix="io-test-") as directory:
    folder = Path(directory)
    current, expected, next_file = [folder / name for name in ("current", "expected", "next")]
    current.write_text("foreign edit")
    expected.write_text("old")
    next_file.write_text("new")
    assert run("replace", current, expected, next_file) == 3
    assert current.read_text() == "foreign edit" and next_file.read_text() == "new"
    print("PASS CAS conflict preserves foreign data")
    expected.write_text("foreign edit")
    assert run("replace", current, expected, next_file) == 0
    assert current.read_text() == "new"
    print("PASS expected CAS atomically replaces the file")
    link = folder / "link"
    link.symlink_to(current)
    next_file.write_text("forbidden")
    assert run("replace", link, expected, next_file) != 0
    assert current.read_text() == "new"
    print("PASS symlink target is refused")
    output = folder / "output"
    assert run("run", 1000, output, "/usr/bin/printf", "%s", "$(touch forbidden);literal") == 0
    assert output.read_text() == "$(touch forbidden);literal"
    assert not (folder / "forbidden").exists()
    print("PASS argv is passed literally without shell interpretation")
    start = time.monotonic()
    assert run("run", 50, output, "/bin/sleep", "10") == 124
    assert time.monotonic() - start < 2
    print("PASS subprocess deadline terminates the command")
    assert run("run", 1000, output, "/usr/bin/yes") != 0
    assert output.stat().st_size <= 1048576
    print("PASS command output is bounded")
    assert run("sync", current) == 0
    assert run("sync", link) != 0
    print("PASS fsync refuses symlinks")
print("NATIVE_IO_TESTS=7")
