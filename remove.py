#!/usr/bin/env python3
"""
清理所有本地运行时文件（数据库、日志、备份、trace）

用法:
    python remove.py           # 交互确认后清理
    python remove.py --yes     # 跳过确认直接清理
    python remove.py --dry-run # 仅列出会删除的文件，不实际删除
"""
import os
import sys
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent

TARGETS = [
    # 数据库文件
    ROOT / "agent_memory.db",
    ROOT / "checkpoints.db",
    ROOT / "code_index.db",
    ROOT / "rollback.db",
    # 日志文件
    ROOT / "agent.log",
    ROOT / "operations.log",
    # Trace 文件
    ROOT / "trace.json",
    # 备份目录
    ROOT / ".agent_backups",
    # Python 缓存（递归清理）
    # (handled separately below)
]

def find_files(targets: list[Path]) -> list[Path]:
    """收集所有存在的待删除目标"""
    found = []
    for t in targets:
        if t.is_file():
            found.append(t)
        elif t.is_dir():
            for f in t.rglob("*"):
                if f.is_file():
                    found.append(f)
            found.append(t)  # 目录本身
    # __pycache__ 目录
    for pycache in ROOT.rglob("__pycache__"):
        if pycache.is_dir():
            found.append(pycache)
    return sorted(found, key=lambda p: str(p))


def fmt_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"


def main():
    dry_run = "--dry-run" in sys.argv
    skip_confirm = "--yes" in sys.argv or "-y" in sys.argv

    targets = find_files(TARGETS)
    
    if not targets:
        print("✅ 没有需要清理的运行文件，工作区已是干净状态。")
        return

    total_size = sum(
        f.stat().st_size for f in targets if f.is_file()
    )

    print(f"📋 将删除 {len(targets)} 个项目 (共 {fmt_size(total_size)}):\n")
    for f in targets:
        if f.is_dir():
            print(f"  📁 {f.relative_to(ROOT)}/")
        else:
            print(f"  📄 {f.relative_to(ROOT)}  ({fmt_size(f.stat().st_size)})")

    if dry_run:
        print("\n🔍 --dry-run 模式：未实际删除")
        return

    if not skip_confirm:
        try:
            answer = input("\n❓ 确认删除以上文件？[y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n⏹️  已取消")
            return
        if answer not in ("y", "yes"):
            print("⏹️  已取消")
            return

    # 执行删除
    deleted = 0
    for f in targets:
        try:
            if f.is_dir():
                shutil.rmtree(f)
            else:
                f.unlink()
            deleted += 1
        except Exception as e:
            print(f"  ⚠️  删除失败: {f.relative_to(ROOT)} — {e}")

    print(f"\n✅ 已清理 {deleted}/{len(targets)} 个项目，释放 {fmt_size(total_size)} 空间。")


if __name__ == "__main__":
    main()
