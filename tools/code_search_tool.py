"""
代码索引搜索工具 - LangChain Tool 封装
"""
from langchain.tools import BaseTool
from pydantic import BaseModel, Field
from typing import Optional
from tools.code_indexer import CodeIndexer


class CodeSearchInput(BaseModel):
    query: str = Field(..., description="Symbol name or keyword to search for")
    search_type: Optional[str] = Field(
        "symbol",
        description="Type of search: 'symbol' (search for classes/functions), 'reference' (find usages), 'file' (search by filename)"
    )
    symbol_type: Optional[str] = Field(
        None,
        description="Filter by symbol type: 'class', 'function', 'method'"
    )


class CodeSearchTool(BaseTool):
    name: str = "code_search"
    description: str = """Search the codebase index for symbols, references, and files.
    
    Uses a pre-built code index to quickly find:
    - Classes, functions, methods by name
    - Symbol references across the codebase
    - Import relationships
    
    Search types:
    - symbol: Search for classes, functions, methods by name
    - reference: Find where a symbol is used/imported
    - file: Search for files by name pattern
    
    Args:
        query: Name or keyword to search for
        search_type: Type of search (default: 'symbol')
        symbol_type: Filter by type ('class', 'function', 'method')
    """
    args_schema: type = CodeSearchInput

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._indexer = CodeIndexer()

    def _run(self, query: str, search_type: str = "symbol", symbol_type: str = None) -> str:
        """Search the code index."""
        try:
            if search_type == "symbol":
                results = self._indexer.search_symbol(query, symbol_type)
                if not results:
                    return f"No symbols found matching '{query}'"
                
                output = [f"Found {len(results)} symbols matching '{query}':\n"]
                for r in results:
                    output.append(f"  {r['type']}: {r['name']} (line {r['line']} in {r['file']})")
                    if r.get('docstring'):
                        docstring_preview = r['docstring'][:100] + '...' if len(r['docstring']) > 100 else r['docstring']
                        output.append(f"    📝 {docstring_preview}")
                
                return "\n".join(output)
            
            elif search_type == "reference":
                results = self._indexer.find_references(query)
                if not results:
                    return f"No references found for '{query}'"
                
                output = [f"Found {len(results)} references to '{query}':\n"]
                for r in results:
                    output.append(f"  📄 {r['file']}:{r['line']} - from {r['module']}")
                    if r.get('names'):
                        output.append(f"    Imports: {', '.join(r['names'])}")
                
                return "\n".join(output)
            
            else:
                return f"Unknown search type: {search_type}. Use 'symbol' or 'reference'."
            
        except Exception as e:
            return f"Error searching code index: {str(e)}"


class IndexCodebaseInput(BaseModel):
    directory: str = Field(..., description="Directory path to index")
    extensions: Optional[str] = Field(
        None,
        description="Comma-separated file extensions to index (e.g., '.py,.js,.ts')"
    )


class IndexCodebaseTool(BaseTool):
    name: str = "index_codebase"
    description: str = """Build or update the code index for a directory.
    
    Scans the directory and indexes:
    - All classes, functions, methods with their signatures
    - Import statements and dependencies
    - File metadata
    
    This must be run before using code_search.
    
    Args:
        directory: Directory to index
        extensions: Comma-separated file extensions (default: .py,.js,.ts,.java)
    """
    args_schema: type = IndexCodebaseInput

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._indexer = CodeIndexer()

    def _run(self, directory: str, extensions: str = None) -> str:
        """Index a codebase directory."""
        try:
            ext_list = None
            if extensions:
                ext_list = [e.strip() for e in extensions.split(',')]
            
            count = self._indexer.index_directory(directory, ext_list)
            stats = self._indexer.get_index_stats()
            
            return (f"✅ Indexed {count} files\n"
                   f"   Total files in index: {stats['files']}\n"
                   f"   Total symbols: {stats['symbols']}\n"
                   f"   Total imports: {stats['imports']}")
            
        except Exception as e:
            return f"Error indexing codebase: {str(e)}"
