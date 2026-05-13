"""代码格式化工具 - AgentScope 格式"""
import asyncio
import os
from agentscope.tool import ToolResponse
from agentscope.message import TextBlock


async def format_code(
    file_path: str,
    formatter: str = "black"
) -> ToolResponse:
    """Format Python code according to style guidelines.
    
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
    
    Returns:
        ToolResponse with format results
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
            return ToolResponse(
                content=[TextBlock(type="text", text=f"Error: Unknown formatter '{formatter}'. Use: black, autopep8, or yapf")]
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
                content=[TextBlock(type="text", text=f"Error: Formatting timed out (30s limit)")]
            )
        
        if process.returncode != 0 and formatter == "black":
            # Black returns 1 if it made changes, 0 if no changes needed
            if process.returncode == 1:
                pass  # Changes were made, which is good
            else:
                stderr_str = stderr.decode('utf-8', errors='replace')
                return ToolResponse(
                    content=[TextBlock(type="text", text=f"Error formatting with {formatter}:\n{stderr_str}")]
                )
        
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
        
        return ToolResponse(
            content=[TextBlock(type="text", text="\n".join(output))]
        )
            
    except FileNotFoundError:
        return ToolResponse(
            content=[TextBlock(type="text", text=f"Error: {formatter} not installed. Install with: pip install {formatter}")]
        )
    except Exception as e:
        return ToolResponse(
            content=[TextBlock(type="text", text=f"Error formatting code: {str(e)}")]
        )
