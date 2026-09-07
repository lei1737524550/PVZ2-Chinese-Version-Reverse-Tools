"""通过 Shizuku/rish 访问 Android 应用私有文件。"""

from __future__ import annotations

import shlex
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath

from domain.errors import ToolError
from infrastructure.files import sha256_file


def shell_quote(value: object) -> str:
    return shlex.quote(str(value))


@dataclass(frozen=True, slots=True)
class AndroidBridge:
    package: str
    rish: str

    def run(self, command: str, *, capture: bool = False, check: bool = False) -> subprocess.CompletedProcess[bytes]:
        if shutil.which(self.rish) is None:
            raise ToolError(f"找不到 {self.rish!r}，请确认 Termux 已配置 Shizuku rish")
        try:
            proc = subprocess.run(
                [self.rish, "-c", command],
                stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=False,
            )
        except OSError as exc:
            raise ToolError(f"执行 {self.rish!r} 失败：{exc}") from exc
        if check and proc.returncode != 0:
            stderr = proc.stderr.decode("utf-8", errors="replace").strip()
            raise ToolError(
                "rish 命令失败。\n"
                f"command   = {command}\n"
                f"exit code = {proc.returncode}\n"
                f"stderr    = {stderr}"
            )
        return proc

    def run_as(self, shell_script: str, *, capture: bool = False, check: bool = False) -> subprocess.CompletedProcess[bytes]:
        command = f"run-as {shell_quote(self.package)} sh -c {shell_quote(shell_script)}"
        return self.run(command, capture=capture, check=check)

    def remote_size(self, path: str, *, retries: int = 3) -> int:
        last_stdout = b""
        last_stderr = b""
        for attempt in range(1, retries + 1):
            proc = self.run_as(f"wc -c < {shell_quote(path)}", capture=True, check=False)
            last_stdout = proc.stdout.strip()
            last_stderr = proc.stderr
            if proc.returncode == 0 and last_stdout:
                try:
                    size = int(last_stdout)
                except ValueError:
                    pass
                else:
                    if size > 0:
                        return size
            if attempt < retries:
                time.sleep(0.5)
        raise ToolError(
            "多次尝试后仍无法获取私有文件大小。\n"
            f"last stdout = {last_stdout!r}\n"
            f"last stderr = {last_stderr.decode('utf-8', errors='replace').strip()}"
        )

    def copy_private_to_shared(self, game_path: str, local_path: Path) -> None:
        local_path.parent.mkdir(parents=True, exist_ok=True)
        part = local_path.with_name(local_path.name + ".part")
        part.unlink(missing_ok=True)
        command = (
            f"run-as {shell_quote(self.package)} cat {shell_quote(game_path)} "
            f"| dd of={shell_quote(part)} bs=64K 2>/dev/null"
        )
        proc = self.run(command, capture=False, check=False)
        if proc.returncode != 0:
            part.unlink(missing_ok=True)
            stderr = proc.stderr.decode("utf-8", errors="replace").strip()
            raise ToolError(f"读取 {game_path} 失败。\nexit={proc.returncode}\nstderr={stderr}")
        if not part.is_file() or part.stat().st_size <= 0:
            part.unlink(missing_ok=True)
            raise ToolError(f"读取完成但本地文件无效：{part}")
        part.replace(local_path)

    def copy_snapshot_to_shared(self, game_path: str, local_path: Path) -> None:
        """先在应用私有目录创建一致性快照，再复制到共享存储。"""
        remote_tmp = game_path + ".extract_snapshot"
        local_part = local_path.with_name(local_path.name + ".part")
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_part.unlink(missing_ok=True)
        success = False
        try:
            self.run_as(
                f"rm -f {shell_quote(remote_tmp)} && cp {shell_quote(game_path)} {shell_quote(remote_tmp)}",
                capture=True,
                check=True,
            )
            expected_size = self.remote_size(remote_tmp)
            pipeline = (
                f"run-as {shell_quote(self.package)} cat {shell_quote(remote_tmp)} "
                f"| dd of={shell_quote(local_part)} bs=4096 2>/dev/null"
            )
            proc = self.run(pipeline, capture=False, check=False)
            if proc.returncode != 0:
                stderr = proc.stderr.decode("utf-8", errors="replace").strip()
                raise ToolError(f"Android shell 管道复制失败。\nexit={proc.returncode}\nstderr={stderr}")
            if not local_part.is_file():
                raise ToolError("管道执行后没有生成临时文件")
            actual_size = local_part.stat().st_size
            if actual_size != expected_size:
                raise ToolError(f"复制长度不一致：remote={expected_size}, local={actual_size}")
            local_part.replace(local_path)
            success = True
        finally:
            try:
                self.run_as(f"rm -f {shell_quote(remote_tmp)}", capture=True, check=False)
            except Exception:
                pass
            if not success:
                local_part.unlink(missing_ok=True)

    def write_shared_to_private(self, source_file: Path, game_path: str) -> None:
        if not source_file.is_file() or source_file.stat().st_size <= 0:
            raise ToolError(f"写入源文件无效：{source_file}")
        remote_tmp = game_path + ".import_tmp"
        inner = (
            f"rm -f {shell_quote(remote_tmp)} && "
            f"cat > {shell_quote(remote_tmp)} && "
            f"chmod 600 {shell_quote(remote_tmp)} && "
            f"mv -f {shell_quote(remote_tmp)} {shell_quote(game_path)}"
        )
        command = (
            f"cat {shell_quote(source_file)} | run-as {shell_quote(self.package)} "
            f"sh -c {shell_quote(inner)}"
        )
        proc = self.run(command, capture=False, check=False)
        if proc.returncode != 0:
            stderr = proc.stderr.decode("utf-8", errors="replace").strip()
            raise ToolError(f"写入 {game_path} 失败。\nexit={proc.returncode}\nstderr={stderr}")

    def private_sha256(self, game_path: str, work_dir: Path, *, required: bool = True) -> str | None:
        temp = work_dir / f".hashcheck_{PurePosixPath(game_path).name}.tmp"
        try:
            self.copy_private_to_shared(game_path, temp)
            return sha256_file(temp)
        except Exception:
            if required:
                raise
            return None
        finally:
            temp.unlink(missing_ok=True)

    def force_stop(self) -> None:
        proc = self.run(f"am force-stop {shell_quote(self.package)}", capture=False, check=False)
        if proc.returncode != 0:
            stderr = proc.stderr.decode("utf-8", errors="replace").strip()
            print(f"WARNING: am force-stop 返回非 0。\nstderr={stderr}")

    def snapshot_private_files(self, work_dir: Path, game_dat: str, game_backup: str | None = None) -> Path:
        backup_dir = work_dir / "backup" / datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir.mkdir(parents=True, exist_ok=True)
        dat_backup = backup_dir / "pp.dat"
        self.copy_private_to_shared(game_dat, dat_backup)
        print("backup :", dat_backup)
        print("sha256 :", sha256_file(dat_backup))
        if game_backup:
            bak_backup = backup_dir / "pp.dat.bak"
            try:
                self.copy_private_to_shared(game_backup, bak_backup)
                print("backup :", bak_backup)
                print("sha256 :", sha256_file(bak_backup))
            except Exception as exc:
                print("WARNING: 原 pp.dat.bak 无法读取：", exc)
        return backup_dir
