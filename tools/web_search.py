"""
Web搜索工具 - 基于 DuckDuckGo 的本地搜索引擎，不依赖 Docker
"""
from langchain.tools import BaseTool
from pydantic import BaseModel, Field
from typing import Optional


class WebSearchInput(BaseModel):
    query: str = Field(..., description="Search query string")
    max_results: Optional[int] = Field(10, description="Maximum number of results to return (1-20)")


class WebSearchTool(BaseTool):
    name: str = "web_search"
    description: str = """Search the web using DuckDuckGo and return results with titles, URLs, and snippets.

Use this tool to find real-time information, documentation, news, or any information 
that isn't in the local codebase.

Args:
    query: The search query (e.g., "Python asyncio best practices")
    max_results: Max results to return (default: 10, max: 20)
"""
    args_schema: type = WebSearchInput

    def _run(self, query: str, max_results: int = 10) -> str:
        """Execute a web search and return formatted results."""
        try:
            from ddgs import DDGS
            
            max_results = min(max(max_results, 1), 20)
            
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=max_results))
            
            if not results:
                return f"No web results found for: '{query}'"
            
            output_lines = [f"🔍 Web search results for: '{query}'", f"Found {len(results)} results:\n"]
            
            for i, r in enumerate(results, 1):
                title = r.get('title', 'No title')
                href = r.get('href', 'No URL')
                body = r.get('body', 'No description')
                # Truncate long snippets
                if len(body) > 200:
                    body = body[:200] + '...'
                
                output_lines.append(f"{i}. **{title}**")
                output_lines.append(f"   🔗 {href}")
                output_lines.append(f"   📝 {body}")
                output_lines.append("")
            
            return "\n".join(output_lines)
            
        except ImportError:
            return "Error: ddgs package not installed. Run: pip install ddgs"
        except Exception as e:
            return f"Error searching web: {str(e)}"
