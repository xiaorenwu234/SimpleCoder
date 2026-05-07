"""
记忆管理工具 - LangChain Tool 封装
"""
from langchain.tools import BaseTool
from pydantic import BaseModel, Field
from typing import Optional
from tools.agent_memory import AgentMemory


class MemoryToolInput(BaseModel):
    action: str = Field(
        ...,
        description="Action to perform: 'save', 'recall', 'list', 'project_save', 'project_recall'"
    )
    key: Optional[str] = Field(None, description="Key to save or recall")
    value: Optional[str] = Field(None, description="Value to save")
    category: Optional[str] = Field("general", description="Category for the memory entry")


class MemoryTool(BaseTool):
    name: str = "agent_memory"
    description: str = """Manage persistent memory across sessions.
    
    Actions:
    - save: Save a key-value pair to memory (persists across sessions)
    - recall: Recall a value by key
    - list: List all saved preferences
    - project_save: Save project-specific context
    - project_recall: Recall project-specific context
    
    Examples:
    - Save: action='save', key='coding_style', value='PEP8 with 120 char lines'
    - Recall: action='recall', key='coding_style'
    - List: action='list'
    
    Args:
        action: Action to perform
        key: Key for save/recall
        value: Value to save
        category: Category (default: 'general')
    """
    args_schema: type = MemoryToolInput

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._memory = AgentMemory()

    def _run(self, action: str, key: str = None, value: str = None, category: str = "general") -> str:
        """Manage agent memory."""
        try:
            import os
            
            if action == "save":
                if not key or value is None:
                    return "Error: 'save' requires both 'key' and 'value'"
                self._memory.set_preference(key, value)
                return f"✅ Saved: {key} = {value}"
            
            elif action == "recall":
                if not key:
                    return "Error: 'recall' requires 'key'"
                result = self._memory.get_preference(key)
                if result is not None:
                    return f"📝 Recalled: {key} = {result}"
                return f"❌ No memory found for key: {key}"
            
            elif action == "list":
                prefs = self._memory.get_all_preferences()
                if not prefs:
                    return "📋 No saved preferences"
                output = ["📋 Saved Preferences:\n"]
                for k, v in prefs.items():
                    output.append(f"  • {k} = {v}")
                return "\n".join(output)
            
            elif action == "project_save":
                if not key or value is None:
                    return "Error: 'project_save' requires both 'key' and 'value'"
                self._memory.set_project_context(os.getcwd(), key, value)
                return f"✅ Saved project context: {key} = {value}"
            
            elif action == "project_recall":
                if not key:
                    # Return full project context
                    ctx = self._memory.get_full_project_context(os.getcwd())
                    if not ctx:
                        return "📋 No project context saved for current directory"
                    output = ["📋 Project Context:\n"]
                    for k, v in ctx.items():
                        output.append(f"  • {k} = {v}")
                    return "\n".join(output)
                result = self._memory.get_project_context(os.getcwd(), key)
                if result is not None:
                    return f"📝 Project context: {key} = {result}"
                return f"❌ No project context found for key: {key}"
            
            else:
                return f"Unknown action: {action}. Use: save, recall, list, project_save, project_recall"
            
        except Exception as e:
            return f"Error: {str(e)}"
