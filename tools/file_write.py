"""文件写入工具 - AgentScope 格式"""
import os
from agentscope.tool import ToolResponse
from agentscope.message import TextBlock


async def write_file(
    file_path: str,
    content: str,
    mode: str = "write"
) -> ToolResponse:
    """Write content to a file.
    
    Modes:
    - write: Overwrite file (default)
    - append: Append to existing file
    
    Will create directories if they don't exist.
    
    Args:
        file_path: Path to file
        content: Content to write
        mode: write or append (default: write)
    
    Returns:
        ToolResponse with result
    """
    try:
        # Resolve relative paths
        if not os.path.isabs(file_path):
            file_path = os.path.join(os.getcwd(), file_path)
        
        # Create directories if needed
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        
        # Write file
        write_mode = "a" if mode == "append" else "w"
        with open(file_path, write_mode, encoding="utf-8") as f:
            f.write(content)
        
        lines = content.count("\n") + 1
        return ToolResponse(
            content=[TextBlock(type="text", text=f"Successfully wrote {lines} lines to {file_path}")]
        )
            
    except Exception as e:
        return ToolResponse(
            content=[TextBlock(type="text", text=f"Error writing file: {str(e)}")]
        )
