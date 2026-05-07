from langchain.tools import BaseTool
from pydantic import BaseModel, Field
from typing import Optional
import subprocess
import os


class GitDiffInput(BaseModel):
    file_path: Optional[str] = Field(None, description="Specific file to show diff for (optional)")
    staged: Optional[bool] = Field(False, description="Show staged changes (default: False for unstaged)")
    stat: Optional[bool] = Field(False, description="Show diffstat summary only")


class GitDiffTool(BaseTool):
    name: str = "git_diff"
    description: str = """Show git diff for changes in the repository.
    
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
    """
    args_schema: type = GitDiffInput

    def _run(self, file_path: str = None, staged: bool = False, stat: bool = False) -> str:
        """Show git diff."""
        try:
            # Check if in git repo
            result = subprocess.run(
                ["git", "rev-parse", "--is-inside-work-tree"],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode != 0:
                return "Error: Not in a Git repository"
            
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
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode != 0:
                return f"Error running git diff:\n{result.stderr}"
            
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
            
            if not result.stdout.strip():
                output.append("✅ No changes found!")
            else:
                output.append(result.stdout)
            
            # Also show untracked files if not showing stat
            if not stat and not file_path:
                untracked = subprocess.run(
                    ["git", "ls-files", "--others", "--exclude-standard"],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                
                if untracked.stdout.strip():
                    output.append("\n📄 Untracked Files:")
                    output.append(untracked.stdout)
            
            return "\n".join(output)
            
        except subprocess.TimeoutExpired:
            return f"Error: Git diff timed out"
        except Exception as e:
            return f"Error running git diff: {str(e)}"
