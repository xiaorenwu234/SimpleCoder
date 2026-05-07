from langchain.tools import BaseTool
from pydantic import BaseModel, Field
from typing import Optional
import subprocess
import os


class RunCommandInput(BaseModel):
    command: str = Field(..., description="Shell command to execute")
    working_dir: Optional[str] = Field(None, description="Working directory for command execution")


class RunCommandTool(BaseTool):
    name: str = "run_command"
    description: str = """Execute a shell command and return the output.
    
    ⚠️  Use with caution - this executes system commands!
    
    Examples:
    - "ls -la" - List files
    - "python script.py" - Run Python script
    - "git status" - Check git status
    
    Args:
        command: Shell command to execute
        working_dir: Working directory (default: current directory)
    """
    args_schema: type = RunCommandInput

    def _run(self, command: str, working_dir: str = None) -> str:
        """Execute shell command."""
        try:
            # Use specified working directory or current directory
            cwd = working_dir if working_dir else os.getcwd()
            
            # Execute command
            result = subprocess.run(
                command,
                shell=True,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=60  # 60 second timeout
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
            
        except subprocess.TimeoutExpired:
            return f"Error: Command timed out (60s limit): {command}"
        except Exception as e:
            return f"Error executing command: {str(e)}"
