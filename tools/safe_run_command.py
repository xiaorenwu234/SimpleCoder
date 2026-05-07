"""
增强版命令执行工具 - 集成沙箱环境、操作日志和自动备份
"""
from langchain.tools import BaseTool
from pydantic import BaseModel, Field
from typing import Optional
import os
from tools.sandbox_executor import SandboxEnvironment, OperationLogger


class SafeRunCommandInput(BaseModel):
    command: str = Field(..., description="Shell command to execute")
    working_dir: Optional[str] = Field(None, description="Working directory for command execution")
    use_sandbox: bool = Field(True, description="Whether to run in sandbox mode (safety checks)")


class SafeRunCommandTool(BaseTool):
    name: str = "safe_run_command"
    description: str = """Execute a shell command safely with sandbox protection.
    
    This is the enhanced version of run_command with:
    - Sandbox execution environment
    - Command whitelist/denylist checking
    - Operation logging
    - Timeout protection
    
    ⚠️  Dangerous commands (rm -rf, sudo, etc.) are blocked by the sandbox.
    
    Examples:
    - "python script.py" - Run Python script
    - "git status" - Check git status
    - "pytest tests/" - Run tests
    
    Args:
        command: Shell command to execute
        working_dir: Working directory (default: current directory)
        use_sandbox: Whether to use sandbox mode (default: True)
    """
    args_schema: type = SafeRunCommandInput

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._sandbox = SandboxEnvironment()
        self._logger = OperationLogger()

    def _run(self, command: str, working_dir: str = None, use_sandbox: bool = True) -> str:
        """Execute shell command with safety checks."""
        try:
            cwd = working_dir if working_dir else os.getcwd()
            
            if use_sandbox:
                # 使用沙箱环境执行
                result = self._sandbox.run_command(command, cwd=cwd)
                
                # 记录操作
                self._logger.log("safe_run_command", {
                    "command": command,
                    "cwd": cwd,
                    "sandbox": True,
                    "success": result["success"]
                })
                
                output = []
                output.append(f"Command: {command}")
                output.append(f"Working Directory: {cwd}")
                output.append(f"Sandbox: {'Enabled' if use_sandbox else 'Disabled'}")
                output.append(f"Exit Code: {result['returncode']}")
                output.append("")
                
                if result["stdout"]:
                    output.append("STDOUT:")
                    output.append(result["stdout"])
                
                if result["stderr"]:
                    output.append("STDERR:")
                    output.append(result["stderr"])
                
                if not result["success"] and result.get("error"):
                    output.append(f"ERROR: {result['error']}")
                
                return "\n".join(output)
            else:
                # 直接执行（不推荐）
                import subprocess
                result = subprocess.run(
                    command,
                    shell=True,
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                    timeout=60
                )
                
                output = []
                output.append(f"Command: {command}")
                output.append(f"Working Directory: {cwd}")
                output.append(f"Exit Code: {result.returncode}")
                output.append("")
                
                if result.stdout:
                    output.append("STDOUT:")
                    output.append(result.stdout)
                
                if result.stderr:
                    output.append("STDERR:")
                    output.append(result.stderr)
                
                return "\n".join(output)
            
        except Exception as e:
            self._logger.log("safe_run_command", {
                "command": command,
                "error": str(e)
            }, success=False)
            return f"Error executing command: {str(e)}"
