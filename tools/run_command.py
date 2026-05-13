"""运行命令工具 - AgentScope 格式"""
import asyncio
import os
from agentscope.tool import ToolResponse
from agentscope.message import TextBlock


async def run_command(
    command: str,
    working_dir: str = None
) -> ToolResponse:
    """Execute a shell command and return the output.
    
    ⚠️  Use with caution - this executes system commands!
    
    Examples:
    - "ls -la" - List files
    - "python script.py" - Run Python script
    - "git status" - Check git status
    
    Args:
        command: Shell command to execute
        working_dir: Working directory (default: current directory)
    
    Returns:
        ToolResponse with command output
    """
    try:
        # Use specified working directory or current directory
        cwd = working_dir if working_dir else os.getcwd()
        
        # Execute command asynchronously
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd
        )
        
        # Wait for completion with timeout
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=60
            )
        except asyncio.TimeoutError:
            process.kill()
            return ToolResponse(
                content=[TextBlock(
                    type="text",
                    text=f"Error: Command timed out (60s limit): {command}"
                )]
            )
        
        # Decode output
        stdout_str = stdout.decode('utf-8', errors='replace')
        stderr_str = stderr.decode('utf-8', errors='replace')
        
        output = []
        output.append(f"Command: {command}")
        output.append(f"Working Directory: {cwd}")
        output.append(f"Exit Code: {process.returncode}")
        output.append("")
        
        if stdout_str:
            output.append("STDOUT:")
            output.append(stdout_str)
        
        if stderr_str:
            output.append("STDERR:")
            output.append(stderr_str)
        
        return ToolResponse(
            content=[TextBlock(type="text", text="\n".join(output))]
        )
            
    except Exception as e:
        return ToolResponse(
            content=[TextBlock(type="text", text=f"Error executing command: {str(e)}")]
        )
