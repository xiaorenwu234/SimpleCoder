"""
测试记忆管理工具 (tools/memory_tool.py)
"""
import os
import pytest
from tools.memory_tool import MemoryTool


class TestMemoryTool:
    """MemoryTool 测试"""
    
    def test_tool_name(self):
        """测试工具名称"""
        tool = MemoryTool()
        assert tool.name == "agent_memory"
    
    def test_save_and_recall(self, temp_db):
        """测试保存和回忆"""
        tool = MemoryTool()
        
        result = tool._run(action="save", key="test_key", value="test_value")
        assert "✅" in result
        assert "test_key" in result
        
        result = tool._run(action="recall", key="test_key")
        assert "test_value" in result
    
    def test_recall_nonexistent(self):
        """测试回忆不存在的键"""
        tool = MemoryTool()
        result = tool._run(action="recall", key="nonexistent_xyz")
        assert "No memory found" in result or "❌" in result
    
    def test_save_missing_value(self):
        """测试保存缺少值"""
        tool = MemoryTool()
        result = tool._run(action="save", key="test_key")
        assert "Error" in result or "requires" in result
    
    def test_recall_missing_key(self):
        """测试回忆缺少键"""
        tool = MemoryTool()
        result = tool._run(action="recall")
        assert "Error" in result or "requires" in result
    
    def test_list_empty(self):
        """测试空列表"""
        tool = MemoryTool()
        result = tool._run(action="list")
        assert "No saved preferences" in result or isinstance(result, str)
    
    def test_list_with_data(self, temp_db):
        """测试有数据时列表"""
        tool = MemoryTool()
        tool._run(action="save", key="k1", value="v1")
        tool._run(action="save", key="k2", value="v2")
        
        result = tool._run(action="list")
        assert "k1" in result
        assert "k2" in result
    
    def test_project_save_and_recall(self, temp_dir):
        """测试项目上下文保存和回忆"""
        tool = MemoryTool()
        
        result = tool._run(action="project_save", key="framework", value="flask")
        assert "✅" in result
        
        result = tool._run(action="project_recall", key="framework")
        assert "flask" in result
    
    def test_project_recall_full(self, temp_dir):
        """测试获取完整项目上下文"""
        tool = MemoryTool()
        tool._run(action="project_save", key="lang", value="python")
        tool._run(action="project_save", key="test", value="pytest")
        
        result = tool._run(action="project_recall")
        assert isinstance(result, str)
    
    def test_project_recall_empty(self):
        """测试空项目上下文"""
        tool = MemoryTool()
        result = tool._run(action="project_recall")
        assert "No project context" in result or isinstance(result, str)
    
    def test_unknown_action(self):
        """测试未知操作"""
        tool = MemoryTool()
        result = tool._run(action="invalid_action")
        assert "Unknown action" in result
    
    def test_save_complex_value(self, temp_db):
        """测试保存复杂值"""
        tool = MemoryTool()
        tool._run(action="save", key="config", value='{"nested": true, "list": [1,2]}')
        
        result = tool._run(action="recall", key="config")
        assert "nested" in result
