from langchain.tools import BaseTool
from pydantic import BaseModel, Field
from typing import Optional
import os


class FileWriteInput(BaseModel):
    file_path: str = Field(..., description="Path to file (absolute or relative)")
    content: str = Field(..., description="Content to write to file")
    mode: Optional[str] = Field("write", description="write (overwrite) or append")


class FileWriteTool(BaseTool):
    name: str = "write_file"
    description: str = """Write content to a file.
    
    Modes:
    - write: Overwrite file (default)
    - append: Append to existing file
    
    Will create directories if they don't exist.
    
    Args:
        file_path: Path to file
        content: Content to write
        mode: write or append (default: write)
    """
    args_schema: type = FileWriteInput

    def _run(self, file_path: str, content: str, mode: str = "write") -> str:
        """Write content to file."""
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
            return f"Successfully wrote {lines} lines to {file_path}"
            
        except Exception as e:
            return f"Error writing file: {str(e)}"
