"""Git差异工具 - AgentScope 格式"""
import asyncio
import os
from typing import Optional
from agentscope.tool import ToolResponse
from agentscope.message import TextBlock


async def git_diff(
    file_path: Optional[str] = None,
    staged: bool = False,
    stat: bool = False
) -> ToolResponse:
    """Show git diff for changes in the repository.
    
    Shows:
    - Added lines (green, prefixed with +)
    - Removed lines (red, prefixed with -)
    - Modified files
    
    Options:
    - No file_path: Show all changes
    - With file_path: Show changes for specific file
    - staged=True: Show staged changes
    - stat=True: Show summary only
    
    Args:
        file_path: Specific file (optional)
        staged: Show staged changes (default: False)
        stat: Show diffstat only (default: False)
    
    Returns:
        ToolResponse with git diff
    """
    try:
        # Check if in git repo
        process = await asyncio.create_subprocess_exec(
            "git", "rev-parse", "--is-inside-work-tree",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            return ToolResponse(
                content=[TextBlock(type="text", text="Error: Not in a Git repository")]
            )
        
        # Build command
        cmd = ["git", "diff"]
        
        if staged:
            cmd.append("--staged")
        
        if stat:
            cmd.append("--stat")
        
        if file_path:
            # Resolve relative paths
            if not os.path.isabs(file_path):
                file_path = os.path.join(os.getcwd(), file_path)
            cmd.append("--")
            cmd.append(file_path)
        
        # Run git diff
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=10
            )
        except asyncio.TimeoutError:
            process.kill()
            return ToolResponse(
                content=[TextBlock(type="text", text="Error: Git diff timed out")]
            )
        
        if process.returncode != 0:
            stderr_str = stderr.decode('utf-8', errors='replace')
            return ToolResponse(
                content=[TextBlock(type="text", text=f"Error running git diff:\n{stderr_str}")]
            )
        
        stdout_str = stdout.decode('utf-8', errors='replace')
        
        output = []
        
        if stat:
            output.append("📊 Diffstat Summary:")
            output.append("")
        else:
            if staged:
                output.append("📝 Staged Changes:")
            else:
                output.append("📝 Unstaged Changes:")
            output.append("")
        
        if not stdout_str.strip():
            output.append("✅ No changes found!")
        else:
            output.append(stdout_str)
        
        # Also show untracked files if not showing stat
        if not stat and not file_path:
            process = await asyncio.create_subprocess_exec(
                "git", "ls-files", "--others", "--exclude-standard",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await process.communicate()
            
            if stdout.strip():
                untracked_str = stdout.decode('utf-8', errors='replace')
                output.append("\n📄 Untracked Files:")
                output.append(untracked_str)
        
        return ToolResponse(
            content=[TextBlock(type="text", text="\n".join(output))]
        )
            
    except Exception as e:
        return ToolResponse(
            content=[TextBlock(type="text", text=f"Error running git diff: {str(e)}")]
        )
