# 配置阿里云百炼 Qwen 模型指南

## 1. 安装依赖

修改完成后，需要重新安装依赖：

```bash
# 使用 pip
pip install -r requirements.txt

# 或者如果你使用 uv
uv sync
```

## 2. 配置环境变量

创建 `.env` 文件：

```bash
cp .env.example .env
```

编辑 `.env` 文件，填入你的阿里云百炼 API Key：

```env
DASHSCOPE_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxx
MODEL_NAME=qwen-plus
```

## 3. 获取 API Key

1. 访问 [阿里云百炼平台](https://bailian.console.aliyun.com/)
2. 登录并进入控制台
3. 在「API-KEY管理」中创建 API Key
4. 复制 API Key 到 `.env` 文件中

## 4. 支持的模型

你可以使用以下模型（在 `MODEL_NAME` 中设置）：

- `qwen-plus` - 通义千问 Plus（推荐，性价比高）
- `qwen-max` - 通义千问 Max（性能更强）
- `qwen-turbo` - 通义千问 Turbo（速度更快）
- `qwen-long` - 通义千问 Long（支持超长上下文）

## 5. 运行项目

```bash
# 运行
python main.py

# 或使用 uv
uv run main.py
```

## 6. 使用其他 OpenAI 兼容接口

如果你想使用其他提供 OpenAI 兼容接口的服务，可以这样配置：

```env
OPENAI_API_KEY=your-api-key
OPENAI_API_BASE=https://your-custom-endpoint.com/v1
MODEL_NAME=your-model-name
```

## 7. 注意事项

- 阿里云百炼的默认 API 地址已内置：`https://dashscope.aliyuncs.com/compatible-mode/v1`
- 如果你使用其他服务商的兼容接口，需要设置 `OPENAI_API_BASE`
- 确保你的 API Key 有足够的配额
- MCP 工具需要 Docker，如果没安装 Docker 会自动跳过，不影响基本使用

## 8. 测试配置

运行后可以尝试以下提示词：
- "你好，请介绍一下自己"
- "帮我写一个 Python 的 Hello World 程序"
- "读取当前目录下的 README.md 文件"
