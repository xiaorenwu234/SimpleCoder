"""
测试跨会话记忆系统 (tools/agent_memory.py)
"""
import os
import json
import pytest
from tools.agent_memory import AgentMemory


class TestAgentMemory:
    """AgentMemory 测试"""
    
    # ========== 用户偏好 ==========
    
    def test_set_and_get_preference(self, temp_db):
        """测试设置和获取偏好"""
        memory = AgentMemory(db_path=temp_db)
        
        memory.set_preference("theme", "dark")
        result = memory.get_preference("theme")
        assert result == "dark"
    
    def test_get_preference_default(self, temp_db):
        """测试获取不存在的偏好返回默认值"""
        memory = AgentMemory(db_path=temp_db)
        
        result = memory.get_preference("nonexistent", "default_val")
        assert result == "default_val"
    
    def test_set_preference_overwrite(self, temp_db):
        """测试覆盖已有偏好"""
        memory = AgentMemory(db_path=temp_db)
        
        memory.set_preference("lang", "python")
        memory.set_preference("lang", "go")
        
        result = memory.get_preference("lang")
        assert result == "go"
    
    def test_get_all_preferences(self, temp_db):
        """测试获取所有偏好"""
        memory = AgentMemory(db_path=temp_db)
        
        memory.set_preference("key1", "val1")
        memory.set_preference("key2", "val2")
        memory.set_preference("key3", "val3")
        
        all_prefs = memory.get_all_preferences()
        assert len(all_prefs) >= 3
        assert all_prefs["key1"] == "val1"
        assert all_prefs["key2"] == "val2"
    
    def test_preference_complex_value(self, temp_db):
        """测试复杂值类型"""
        memory = AgentMemory(db_path=temp_db)
        
        memory.set_preference("config", {"nested": {"key": "value"}, "list": [1, 2, 3]})
        result = memory.get_preference("config")
        assert result["nested"]["key"] == "value"
        assert result["list"] == [1, 2, 3]
    
    # ========== 项目上下文 ==========
    
    def test_set_and_get_project_context(self, temp_dir, temp_db):
        """测试设置和获取项目上下文"""
        memory = AgentMemory(db_path=temp_db)
        
        memory.set_project_context(temp_dir, "framework", "django")
        result = memory.get_project_context(temp_dir, "framework")
        assert result == "django"
    
    def test_get_project_context_default(self, temp_dir, temp_db):
        """测试获取不存在的项目上下文"""
        memory = AgentMemory(db_path=temp_db)
        
        result = memory.get_project_context(temp_dir, "nonexistent", "default")
        assert result == "default"
    
    def test_get_full_project_context(self, temp_dir, temp_db):
        """测试获取完整项目上下文"""
        memory = AgentMemory(db_path=temp_db)
        
        memory.set_project_context(temp_dir, "language", "python")
        memory.set_project_context(temp_dir, "test_runner", "pytest")
        
        ctx = memory.get_full_project_context(temp_dir)
        assert ctx["language"] == "python"
        assert ctx["test_runner"] == "pytest"
    
    def test_project_context_isolation(self, temp_db):
        """测试不同项目上下文隔离"""
        memory = AgentMemory(db_path=temp_db)
        
        memory.set_project_context("/project/a", "name", "Project A")
        memory.set_project_context("/project/b", "name", "Project B")
        
        assert memory.get_project_context("/project/a", "name") == "Project A"
        assert memory.get_project_context("/project/b", "name") == "Project B"
    
    # ========== 对话历史 ==========
    
    def test_add_conversation(self, temp_db):
        """测试添加对话记录"""
        memory = AgentMemory(db_path=temp_db)
        
        memory.add_conversation("session1", "user", "Hello")
        memory.add_conversation("session1", "assistant", "Hi there!")
        
        history = memory.get_conversation_history("session1")
        assert len(history) == 2
        assert history[0]["role"] == "user"
        assert history[0]["content"] == "Hello"
        assert history[1]["role"] == "assistant"
    
    def test_conversation_history_limit(self, temp_db):
        """测试对话历史数量限制"""
        memory = AgentMemory(db_path=temp_db)
        
        for i in range(20):
            memory.add_conversation("session1", "user", f"msg {i}")
        
        history = memory.get_conversation_history("session1", limit=5)
        assert len(history) == 5
    
    def test_conversation_session_isolation(self, temp_db):
        """测试不同会话隔离"""
        memory = AgentMemory(db_path=temp_db)
        
        memory.add_conversation("s1", "user", "msg for s1")
        memory.add_conversation("s2", "user", "msg for s2")
        
        h1 = memory.get_conversation_history("s1")
        h2 = memory.get_conversation_history("s2")
        
        assert len(h1) == 1
        assert len(h2) == 1
        assert h1[0]["content"] == "msg for s1"
    
    def test_conversation_metadata(self, temp_db):
        """测试对话元数据"""
        memory = AgentMemory(db_path=temp_db)
        
        memory.add_conversation("s1", "user", "test", metadata={"tool": "search"})
        history = memory.get_conversation_history("s1")
        
        assert len(history) == 1
        assert history[0]["metadata"]["tool"] == "search"
    
    def test_get_recent_context(self, temp_db):
        """测试获取最近上下文"""
        memory = AgentMemory(db_path=temp_db)
        
        for i in range(10):
            memory.add_conversation("s1", "user", f"message number {i}")
        
        context = memory.get_recent_context("s1", max_tokens=1000)
        assert len(context) > 0
        assert "message" in context
    
    # ========== 学习到的知识 ==========
    
    def test_add_and_get_knowledge(self, temp_db):
        """测试添加和获取知识"""
        memory = AgentMemory(db_path=temp_db)
        
        memory.add_knowledge("pattern", "singleton", "Use module-level variable")
        result = memory.get_knowledge("pattern", "singleton")
        assert "singleton" in result
        assert result["singleton"]["value"] == "Use module-level variable"
    
    def test_get_knowledge_by_category(self, temp_db):
        """测试按类别获取知识"""
        memory = AgentMemory(db_path=temp_db)
        
        memory.add_knowledge("pattern", "factory", "Factory pattern info")
        memory.add_knowledge("pattern", "observer", "Observer pattern info")
        memory.add_knowledge("language", "python", "Python info")
        
        patterns = memory.get_knowledge("pattern")
        assert len(patterns) >= 2
        assert "factory" in patterns
        assert "observer" in patterns
        
        langs = memory.get_knowledge("language")
        assert "python" in langs
    
    def test_knowledge_usage_count(self, temp_db):
        """测试知识使用计数"""
        memory = AgentMemory(db_path=temp_db)
        
        memory.add_knowledge("cat", "key1", "value1")
        memory.add_knowledge("cat", "key1", "value2")  # update
        
        result = memory.get_knowledge("cat", "key1")
        assert result["key1"]["usage_count"] >= 1
    
    # ========== 工具使用统计 ==========
    
    def test_record_tool_usage(self, temp_db):
        """测试记录工具使用"""
        memory = AgentMemory(db_path=temp_db)
        
        memory.record_tool_usage("search", success=True, execution_time=0.5)
        memory.record_tool_usage("search", success=True, execution_time=0.3)
        memory.record_tool_usage("search", success=False, execution_time=1.0)
        
        stats = memory.get_tool_stats()
        assert "search" in stats
        assert stats["search"]["success_count"] == 2
        assert stats["search"]["failure_count"] == 1
    
    def test_tool_stats_multiple_tools(self, temp_db):
        """测试多工具统计"""
        memory = AgentMemory(db_path=temp_db)
        
        memory.record_tool_usage("tool_a", success=True, execution_time=0.1)
        memory.record_tool_usage("tool_b", success=True, execution_time=0.2)
        
        stats = memory.get_tool_stats()
        assert "tool_a" in stats
        assert "tool_b" in stats
    
    # ========== 清理和维护 ==========
    
    def test_cleanup_old_data(self, temp_db):
        """测试清理旧数据"""
        memory = AgentMemory(db_path=temp_db)
        
        # 添加数据
        memory.add_conversation("s1", "user", "old message")
        memory.set_preference("keep", "this")
        
        # 清理（0天 = 清理所有旧对话）
        memory.cleanup_old_data(days=0)
        
        # 偏好应该保留
        assert memory.get_preference("keep") == "this"
    
    def test_export_memory(self, temp_dir, temp_db):
        """测试导出记忆"""
        memory = AgentMemory(db_path=temp_db)
        
        memory.set_preference("key1", "val1")
        memory.add_knowledge("cat1", "k1", "v1")
        
        export_path = os.path.join(temp_dir, "memory_export.json")
        memory.export_memory(export_path)
        
        assert os.path.exists(export_path)
        with open(export_path, "r") as f:
            data = json.load(f)
        assert "preferences" in data
        assert "knowledge" in data
        assert data["preferences"]["key1"] == "val1"
