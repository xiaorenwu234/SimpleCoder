from langchain.tools import BaseTool
from pydantic import BaseModel, Field
from typing import Optional
import os
import fnmatch


class SearchFilesInput(BaseModel):
    path: Optional[str] = Field(".", description="Directory to search in")
    pattern: str = Field("*.py", description="File pattern to match (e.g., *.py, *.txt)")
    recursive: Optional[bool] = Field(True, description="Search recursively")


class SearchFilesTool(BaseTool):
    name: str = "search_files"
    description: str = """Search for files matching a pattern.
    
    Uses glob patterns for matching.
    
    Examples:
    - "*.py" - All Python files
    - "*.txt" - All text files
    - "test_*" - Files starting with test_
    
    Args:
        path: Directory to search (default: current directory)
        pattern: Glob pattern (default: *.py)
        recursive: Search recursively (default: True)
    """
    args_schema: type = SearchFilesInput

    def _run(self, pattern: str = "*.py", path: str = ".", recursive: bool = True) -> str:
        """Search for files."""
        try:
            # Resolve relative paths
            if not os.path.isabs(path):
                path = os.path.join(os.getcwd(), path)
            
            if not os.path.exists(path):
                return f"Error: Directory not found: {path}"
            
            matched_files = []
            
            if recursive:
                for root, dirs, files in os.walk(path):
                    for filename in files:
                        if fnmatch.fnmatch(filename, pattern):
                            file_path = os.path.join(root, filename)
                            try:
                                size = os.path.getsize(file_path)
                                matched_files.append((file_path, size))
                            except:
                                matched_files.append((file_path, 0))
            else:
                for filename in os.listdir(path):
                    if fnmatch.fnmatch(filename, pattern):
                        file_path = os.path.join(path, filename)
                        try:
                            size = os.path.getsize(file_path)
                            matched_files.append((file_path, size))
                        except:
                            matched_files.append((file_path, 0))
            
            if not matched_files:
                return f"No files matching '{pattern}' in {path}"
            
            # Format output
            result = [f"Found {len(matched_files)} files matching '{pattern}':", ""]
            for file_path, size in matched_files:
                size_str = self._format_size(size)
                result.append(f"📄 {file_path} ({size_str})")
            
            return "\n".join(result)
            
        except Exception as e:
            return f"Error searching files: {str(e)}"
    
    def _format_size(self, size: int) -> str:
        """Format file size."""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"
