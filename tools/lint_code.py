"""代码检查工具 - AgentScope 格式"""
import asyncio
import os
from agentscope.tool import ToolResponse
from agentscope.message import TextBlock


async def lint_code(
    file_path: str,
    linter: str = "flake8"
) -> ToolResponse:
    """Check Python code for errors and style issues.
    
    Supported linters:
    - flake8: Fast style and error checking (default)
    - pylint: Comprehensive code analysis
    - pyflakes: Simple error detection
    
    Checks for:
    - Syntax errors
    - Unused imports
    - Style violations
    - Potential bugs
    - Code complexity
    
    Args:
        file_path: Path to Python file
        linter: Linter name (default: flake8)
    
    Returns:
        ToolResponse with lint results
    """
    try:
        # Resolve relative paths
        if not os.path.isabs(file_path):
            file_path = os.path.join(os.getcwd(), file_path)
        
        if not os.path.exists(file_path):
            return ToolResponse(
                content=[TextBlock(type="text", text=f"Error: File not found: {file_path}")]
            )
        
        if not file_path.endswith(".py"):
            return ToolResponse(
                content=[TextBlock(type="text", text=f"Warning: File is not a Python file (.py)")]
            )
        
        # Run linter
        if linter == "flake8":
            cmd = ["flake8", "--max-line-length=120", "--statistics", file_path]
        elif linter == "pylint":
            cmd = ["pylint", "--max-line-length=120", file_path]
        elif linter == "pyflakes":
            cmd = ["pyflakes", file_path]
        else:
            return ToolResponse(
                content=[TextBlock(type="text", text=f"Error: Unknown linter '{linter}'. Use: flake8, pylint, or pyflakes")]
            )
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=30
            )
        except asyncio.TimeoutError:
            process.kill()
            return ToolResponse(
                content=[TextBlock(type="text", text=f"Error: Linting timed out (30s limit)")]
            )
        
        stdout_str = stdout.decode('utf-8', errors='replace')
        stderr_str = stderr.decode('utf-8', errors='replace')
        
        output = []
        output.append(f"Linter: {linter}")
        output.append(f"File: {file_path}")
        output.append(f"Exit Code: {process.returncode}")
        output.append("")
        
        if process.returncode == 0:
            output.append("✅ No issues found!")
        else:
            if stdout_str:
                output.append("Issues found:")
                output.append(stdout_str)
            
            if stderr_str:
                output.append("Errors:")
                output.append(stderr_str)
        
        return ToolResponse(
            content=[TextBlock(type="text", text="\n".join(output))]
        )
            
    except FileNotFoundError:
        return ToolResponse(
            content=[TextBlock(type="text", text=f"Error: {linter} not installed. Install with: pip install {linter}")]
        )
    except Exception as e:
        return ToolResponse(
            content=[TextBlock(type="text", text=f"Error running linter: {str(e)}")]
        )
