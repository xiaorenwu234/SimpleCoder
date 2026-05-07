"""
沙箱执行环境 - 提供安全的命令执行和文件操作
"""
import subprocess
import os
import tempfile
import shutil
from typing import Optional, Tuple
from pathlib import Path


class SandboxEnvironment:
    """沙箱环境执行器"""
    
    def __init__(self, work_dir: Optional[str] = None, timeout: int = 30):
        self.timeout = timeout
        self.work_dir = work_dir or tempfile.mkdtemp(prefix="sandbox_")
        self._created_dir = work_dir is None
        
        # 确保工作目录存在
        os.makedirs(self.work_dir, exist_ok=True)
        
        # 白名单命令
        self.allowed_commands = {
            'python', 'python3', 'pip', 'pytest', 'flake8', 'pylint',
            'black', 'git', 'ls', 'cat', 'grep', 'find', 'wc', 'head',
            'tail', 'echo', 'mkdir', 'touch', 'cp', 'mv'
        }
        
        # 危险命令
        self.dangerous_commands = {
            'rm -rf', 'rm -f', 'sudo', 'chmod', 'chown',
            'mkfs', 'fdisk', 'dd', 'shutdown', 'reboot'
        }
    
    def is_command_safe(self, command: str) -> Tuple[bool, str]:
        """检查命令是否安全"""
        cmd_lower = command.lower().strip()
        
        # 检查危险命令
        for dangerous in self.dangerous_commands:
            if dangerous in cmd_lower:
                return False, f"命令包含危险操作: {dangerous}"
        
        # 检查白名单
        base_cmd = cmd_lower.split()[0] if cmd_lower else ''
        if base_cmd not in self.allowed_commands:
            return False, f"命令 '{base_cmd}' 不在白名单中"
        
        return True, "命令安全检查通过"
    
    def run_command(self, command: str, cwd: Optional[str] = None) -> dict:
        """在沙箱中执行命令"""
        # 安全检查
        is_safe, message = self.is_command_safe(command)
        if not is_safe:
            return {
                "success": False,
                "error": message,
                "stdout": "",
                "stderr": "",
                "returncode": -1
            }
        
        # 确定工作目录
        exec_dir = cwd or self.work_dir
        
        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=exec_dir,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                # 限制资源
                preexec_fn=os.setsid if hasattr(os, 'setsid') else None
            )
            
            return {
                "success": result.returncode == 0,
                "error": result.stderr if result.returncode != 0 else "",
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode
            }
            
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "error": f"命令执行超时 ({self.timeout}s)",
                "stdout": "",
                "stderr": "",
                "returncode": -1
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "stdout": "",
                "stderr": "",
                "returncode": -1
            }
    
    def safe_file_read(self, file_path: str, max_size: int = 1024 * 1024) -> dict:
        """安全地读取文件"""
        try:
            # 解析路径
            abs_path = os.path.abspath(file_path)
            
            # 检查文件是否存在
            if not os.path.exists(abs_path):
                return {"success": False, "error": "文件不存在"}
            
            # 检查文件大小
            file_size = os.path.getsize(abs_path)
            if file_size > max_size:
                return {
                    "success": False,
                    "error": f"文件过大 ({file_size} bytes > {max_size} bytes)"
                }
            
            # 读取文件
            with open(abs_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            return {
                "success": True,
                "content": content,
                "size": file_size
            }
            
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def safe_file_write(self, file_path: str, content: str) -> dict:
        """安全地写入文件"""
        try:
            # 解析路径
            abs_path = os.path.abspath(file_path)
            
            # 确保目录存在
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)
            
            # 写入文件
            with open(abs_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            return {
                "success": True,
                "path": abs_path,
                "size": len(content)
            }
            
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def cleanup(self):
        """清理沙箱环境"""
        if self._created_dir and os.path.exists(self.work_dir):
            shutil.rmtree(self.work_dir, ignore_errors=True)
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()
    
    def __del__(self):
        self.cleanup()


class OperationLogger:
    """操作日志记录器"""
    
    def __init__(self, log_file: str = "operations.log"):
        self.log_file = log_file
    
    def log(self, operation: str, details: dict, success: bool = True):
        """记录操作日志"""
        import json
        from datetime import datetime
        
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "operation": operation,
            "success": success,
            "details": details
        }
        
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
