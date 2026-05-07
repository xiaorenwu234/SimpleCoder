from langchain.tools import BaseTool
from pydantic import BaseModel, Field
from typing import Optional
import subprocess
import os


class LintCodeInput(BaseModel):
    file_path: str = Field(..., description="Path to the Python file to lint")
    linter: Optional[str] = Field("flake8", description="Linter to use: flake8, pylint, or pyflakes")


class LintCodeTool(BaseTool):
    name: str = "lint_code"
    description: str = """Check Python code for errors and style issues.
    
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
    """
    args_schema: type = LintCodeInput

    def _run(self, file_path: str, linter: str = "flake8") -> str:
        """Lint Python code."""
        try:
            # Resolve relative paths
            if not os.path.isabs(file_path):
                file_path = os.path.join(os.getcwd(), file_path)
            
            if not os.path.exists(file_path):
                return f"Error: File not found: {file_path}"
            
            if not file_path.endswith(".py"):
                return f"Warning: File is not a Python file (.py)"
            
            # Run linter
            if linter == "flake8":
                cmd = ["flake8", "--max-line-length=120", "--statistics", file_path]
            elif linter == "pylint":
                cmd = ["pylint", "--max-line-length=120", file_path]
            elif linter == "pyflakes":
                cmd = ["pyflakes", file_path]
            else:
                return f"Error: Unknown linter '{linter}'. Use: flake8, pylint, or pyflakes"
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            output = []
            output.append(f"Linter: {linter}")
            output.append(f"File: {file_path}")
            output.append(f"Exit Code: {result.returncode}")
            output.append("")
            
            if result.returncode == 0:
                output.append("✅ No issues found!")
            else:
                if result.stdout:
                    output.append("Issues found:")
                    output.append(result.stdout)
                
                if result.stderr:
                    output.append("Errors:")
                    output.append(result.stderr)
            
            return "\n".join(output)
            
        except subprocess.TimeoutExpired:
            return f"Error: Linting timed out (30s limit)"
        except FileNotFoundError:
            return f"Error: {linter} not installed. Install with: pip install {linter}"
        except Exception as e:
            return f"Error running linter: {str(e)}"
