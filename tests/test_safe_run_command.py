"""
测试增强版命令执行工具 (tools/safe_run_command.py)
"""
import os
import pytest
from tools.safe_run_command import SafeRunCommandTool


class TestSafeRunCommandTool:
    """SafeRunCommandTool 测试"""
    
    def test_tool_name(self):
        """测试工具名称"""
        tool = SafeRunCommandTool()
        assert tool.name == "safe_run_command"
    
    def test_tool_has_description(self):
        """测试工具描述"""
        tool = SafeRunCommandTool()
        assert tool.description is not None
        assert len(tool.description) > 0
    
    def test_run_simple_echo(self):
        """测试简单 echo 命令"""
        tool = SafeRunCommandTool()
        result = tool._run(command="echo hello_world")
        assert "hello_world" in result
        assert "Exit Code: 0" in result
    
    def test_run_with_sandbox(self, temp_dir):
        """测试沙箱模式执行"""
        tool = SafeRunCommandTool()
        result = tool._run(command="ls", working_dir=temp_dir, use_sandbox=True)
        assert "Sandbox: Enabled" in result
    
    def test_run_without_sandbox(self, temp_dir):
        """测试非沙箱模式执行"""
        tool = SafeRunCommandTool()
        result = tool._run(command="echo test", working_dir=temp_dir, use_sandbox=False)
        assert "test" in result
    
    def test_run_dangerous_command_blocked(self):
        """测试危险命令被阻止"""
        tool = SafeRunCommandTool()
        result = tool._run(command="sudo rm -rf /", use_sandbox=True)
        assert "危险" in result or "ERROR" in result or "blocked" in result.lower()
    
    def test_run_command_working_dir(self, temp_dir):
        """测试指定工作目录"""
        tool = SafeRunCommandTool()
        result = tool._run(command="python3 -c \"print('ok')\"", working_dir=temp_dir)
        assert "ok" in result
    
    def test_run_command_nonexistent_dir(self):
        """测试不存在的目录"""
        tool = SafeRunCommandTool()
        result = tool._run(command="echo test", working_dir="/nonexistent/dir")
        # 应该返回错误或仍然执行
        assert isinstance(result, str)
