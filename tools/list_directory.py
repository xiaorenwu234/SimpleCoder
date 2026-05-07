from langchain.tools import BaseTool
from pydantic import BaseModel, Field
from typing import Optional
import os


class ListDirectoryInput(BaseModel):
    path: Optional[str] = Field(".", description="Directory path to list (default: current directory)")
    recursive: Optional[bool] = Field(False, description="List recursively")


class ListDirectoryTool(BaseTool):
    name: str = "list_directory"
    description: str = """List contents of a directory.
    
    Shows files and directories with sizes.
    
    Args:
        path: Directory path (default: current directory)
        recursive: List recursively (default: False)
    """
    args_schema: type = ListDirectoryInput

    def _run(self, path: str = ".", recursive: bool = False) -> str:
        """List directory contents."""
        try:
            # Resolve relative paths
            if not os.path.isabs(path):
                path = os.path.join(os.getcwd(), path)
            
            if not os.path.exists(path):
                return f"Error: Directory not found: {path}"
            
            if not os.path.isdir(path):
                return f"Error: Not a directory: {path}"
            
            result = []
            
            if recursive:
                for root, dirs, files in os.walk(path):
                    level = root.replace(path, "").count(os.sep)
                    indent = "  " * level
                    result.append(f"{indent}📁 {os.path.basename(root)}/")
                    
                    subindent = "  " * (level + 1)
                    for file in files:
                        file_path = os.path.join(root, file)
                        try:
                            size = os.path.getsize(file_path)
                            size_str = self._format_size(size)
                            result.append(f"{subindent}📄 {file} ({size_str})")
                        except:
                            result.append(f"{subindent}📄 {file}")
            else:
                items = os.listdir(path)
                items.sort()
                
                for item in items:
                    item_path = os.path.join(path, item)
                    if os.path.isdir(item_path):
                        result.append(f"📁 {item}/")
                    else:
                        try:
                            size = os.path.getsize(item_path)
                            size_str = self._format_size(size)
                            result.append(f"📄 {item} ({size_str})")
                        except:
                            result.append(f"📄 {item}")
            
            return f"Directory: {path}\n" + "\n".join(result)
            
        except Exception as e:
            return f"Error listing directory: {str(e)}"
    
    def _format_size(self, size: int) -> str:
        """Format file size."""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"
