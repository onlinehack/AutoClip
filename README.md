# 🚀 AutoClip Studio - 自动化视频混剪系统

AutoClip Studio 是一个基于 Python 和 Streamlit 的全自动化视频生成工具。它能够根据您输入的文案脚本，自动匹配并在多个素材库中抽取视频片段，结合 TTS 语音合成与背景音乐，一键生成高质量的短视频。

## ✨ 功能特性

*   **智能混剪**：支持从多个视频素材文件夹中随机抽取片段进行混剪。
*   **灵活编排**：自定义素材文件夹的**播放顺序**和**时长权重**（百分比），精准控制视频节奏。
*   **语音合成**：集成 Edge TTS，支持多种高质量语音角色（如 Xiaoxiao, Yunxi, Aria 等）。
*   **背景音乐**：支持自动混音 BGM，可从 `assets/bgm` 目录选择。
*   **批量生成**：支持一次性生成多个不同版本的视频。
*   **多分辨率支持**：
    *   TikTok / Shorts / Reels (1080x1920)
    *   横屏视频 (1920x1080)
    *   自定义分辨率
*   **可视化界面**：提供直观的 Streamlit Web 界面，实时预览配置与生成结果。

## 📂 目录结构

```text
moviecut/
├── assets/                 # 素材存放目录
│   ├── video/              # 视频素材（请在此创建子文件夹分类存放）
│   └── bgm/                # 背景音乐 (.mp3, .wav)
├── deploy/                 # 部署相关文件
│   ├── Dockerfile
│   └── docker-compose.yml
├── output/                 # 视频生成输出目录
├── src/                    # 核心代码库
│   ├── pipeline.py         # 核心处理流程
│   ├── models.py           # 数据模型
│   └── processors/         # 各类处理器
├── gui_app.py              # Streamlit 启动入口
├── requirements.txt        # 依赖列表
└── README.md               # 项目说明文档
```

## 🛠️ 安装与运行

### 方式一：本地运行 (Local)

1.  **环境准备**：确保已安装 Python 3.8+。
2.  **安装依赖**：
    ```bash
    pip install -r requirements.txt
    ```
3.  **准备素材**：
    *   在 `assets/video/` 下创建子文件夹（例如 `scene1`, `scene2`），并放入视频片段。
    *   在 `assets/bgm/` 下放入背景音乐（可选）。
4.  **启动应用**：
    ```bash
    streamlit run gui_app.py
    ```
    启动后浏览器会自动打开 `http://localhost:8501`。

### 方式二：Docker 部署

本项目提供了 Docker 支持，可轻松隔离环境运行。

1.  **进入部署目录**（或在根目录使用指定文件）：
    ```bash
    cd deploy
    ```
    *注意：如果要在根目录构建，可能需要调整 `docker-compose.yml` 中的上下文路径，或者直接使用以下命令：*

    **推荐：在根目录下直接构建运行**
    确保 `docker-compose.yml` (如果位于 `deploy/` 中) 指向正确的构建上下文，或者使用简单的 Docker 命令：

    ```bash
    docker build -t autoclip-studio -f deploy/Dockerfile .
    docker run -p 8501:8501 -v $(pwd)/assets:/app/assets -v $(pwd)/output:/app/output autoclip-studio
    ```

    或者使用 `docker-compose` (需确保 `deploy/docker-compose.yml` 配置正确映射了上级目录)：
    ```bash
    docker-compose -f deploy/docker-compose.yml up --build -d
    ```

## 📖 使用指南

1.  **脚本设置**：在左侧输入您的视频文案脚本 (Prompt/Script)。
2.  **选择语音**：在侧边栏选择您喜欢的配音角色。
3.  **配置素材**：
    *   系统会自动读取 `assets/video` 下的子文件夹。
    *   在界面右侧勾选需要使用的素材文件夹。
    *   **拖动排序**：决定素材出现的先后顺序。
    *   **调整权重**：滑动滑块决定该类素材在视频中占据的时长比例。
4.  **开始生成**：点击“🎬 开始生成”按钮。
5.  **预览与导出**：生成完成后，视频将直接在界面展示，文件保存在 `output/` 目录。

## ⚠️ 注意事项

*   请确保 `assets/video` 目录下至少有一个包含视频文件的子文件夹，否则无法生成。
*   生成的视频默认使用 GPU 加速（如果环境支持且配置了相关库），否则使用 CPU，速度可能较慢。
*   初次运行可能会下载 ImageMagick 策略或其他依赖模型，请保持网络通畅。

---
Enjoy creating! 🎥
