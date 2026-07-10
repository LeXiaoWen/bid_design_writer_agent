API_PRESETS = {
    "OpenAI": {
        "provider": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o",
    },
    "DeepSeek": {
        "provider": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-v4-flash",
    },
    "通义千问 DashScope": {
        "provider": "通义千问 DashScope",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",
    },
    "硅基流动 SiliconFlow": {
        "provider": "硅基流动 SiliconFlow",
        "base_url": "https://api.siliconflow.cn/v1",
        "model": "deepseek-ai/DeepSeek-V3",
    },
    "OpenRouter": {
        "provider": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "model": "openai/gpt-4o-mini",
    },
    "自定义": {
        "provider": "自定义",
        "base_url": "",
        "model": "",
    },
}

TEMPLATE_FILES = {
    "12-chapter": "设计标书大纲模板参考.md",
    "5-chapter": "设计标书大纲模板参考-全过程咨询标.md",
}

STAGE_LABELS = {
    "init": "等待上传",
    "uploaded": "已上传",
    "confirming": "信息确认",
    "template_select": "模板选择",
    "generating": "方案生成",
    "done": "已完成",
}
