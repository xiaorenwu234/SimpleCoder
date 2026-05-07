from langchain.tools import BaseTool
from pydantic import BaseModel, Field
from typing import Optional
import subprocess
import os


class FormatCodeInput(BaseModel):
    file_path: str = Field(..., description="Path to the Python file to format")
    formatter: Optional[str] = Field("black", description="Formatter to use: black, autopep8, or yapf")


class FormatCodeTool(BaseTool):
    name: str = "format_code"
    description: str = """Format Python code according to style guidelines.
    
    Supported formatters:
    - black: The uncompromising code formatter (default)
    - autopep8: Automatically formats Python code to PEP 8
    - yapf: Yet Another Python Formatter
    
    Benefits:
    - Consistent code style
    - PEP 8 compliance
    - Improved readability
    - Automatic formatting
    
    Args:
        file_path: Path to Python file
        formatter: Formatter name (default: black)
    """
    args_schema: type = FormatCodeInput

    def _run(self, file_path: str, formatter: str = "black") -> str:
        """Format Python code."""
        try:
            # Resolve relative paths
            if not os.path.isabs(file_path):
                file_path = os.path.join(os.getcwd(), file_path)
            
            if not os.path.exists(file_path):
                return f"Error: File not found: {file_path}"
            
            if not file_path.endswith(".py"):
                return f"Warning: File is not a Python file (.py)"
            
            # Read original content
            with open(file_path, "r", encoding="utf-8") as f:
                original = f.read()
            
            # Run formatter
            if formatter == "black":
                cmd = ["black", "--line-length=120", "--quiet", file_path]
            elif formatter == "autopep8":
                cmd = ["autopep8", "--in-place", "--max-line-length=120", file_path]
            elif formatter == "yapf":
                cmd = ["yapf", "--in-place", file_path]
            else:
                return f"Error: Unknown formatter '{formatter}'. Use: black, autopep8, or yapf"
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode != 0 and formatter == "black":
                # Black returns 1 if it made changes, 0 if no changes needed
                if result.returncode == 1:
                    pass  # Changes were made, which is good
                else:
                    return f"Error formatting with {formatter}:\n{result.stderr}"
            
            # Read formatted content
            with open(file_path, "r", encoding="utf-8") as f:
                formatted = f.read()
            
            # Calculate stats
            original_lines = original.count("\n") + 1
            formatted_lines = formatted.count("\n") + 1
            changes = abs(original_lines - formatted_lines)
            
            output = []
            output.append(f"Formatter: {formatter}")
            output.append(f"File: {file_path}")
            output.append(f"Original lines: {original_lines}")
            output.append(f"Formatted lines: {formatted_lines}")
            
            if original == formatted:
                output.append("\n✅ Code is already properly formatted!")
            else:
                output.append(f"\n✅ Code formatted successfully!")
                if changes > 0:
                    output.append(f"   Lines changed: ±{changes}")
            
            return "\n".join(output)
            
        except subprocess.TimeoutExpired:
            return f"Error: Formatting timed out (30s limit)"
        except FileNotFoundError:
            return f"Error: {formatter} not installed. Install with: pip install {formatter}"
        except Exception as e:
            return f"Error formatting code: {str(e)}"
