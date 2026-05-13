"""Web搜索工具 - AgentScope 格式
基于 DuckDuckGo 的本地搜索引擎，不依赖 Docker
"""
import asyncio
from typing import Optional
from agentscope.tool import ToolResponse
from agentscope.message import TextBlock


async def web_search(
    query: str,
    max_results: int = 10
) -> ToolResponse:
    """Search the web using DuckDuckGo and return results with titles, URLs, and snippets.

Use this tool to find real-time information, documentation, news, or any information 
that isn't in the local codebase.

Args:
    query: The search query (e.g., "Python asyncio best practices")
    max_results: Max results to return (default: 10, max: 20)

Returns:
    ToolResponse with search results
"""
    try:
        from ddgs import DDGS
        
        max_results = min(max(max_results, 1), 20)
        
        # DDGS 是同步的，使用 to_thread 避免阻塞
        def search_sync():
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=max_results))
            return results
        
        results = await asyncio.to_thread(search_sync)
        
        if not results:
            return ToolResponse(
                content=[TextBlock(type="text", text=f"No web results found for: '{query}'")]
            )
        
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
        
        return ToolResponse(
            content=[TextBlock(type="text", text="\n".join(output_lines))]
        )
            
    except ImportError:
        return ToolResponse(
            content=[TextBlock(type="text", text="Error: ddgs package not installed. Run: pip install ddgs")]
        )
    except Exception as e:
        return ToolResponse(
            content=[TextBlock(type="text", text=f"Error searching web: {str(e)}")]
        )
