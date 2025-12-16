# 🚀 AutoClip Studio - 自动化视频混剪系统 (Audio Driven)

AutoClip Studio 是一个基于 Python 和 Streamlit 的全自动化视频生成工具。它改为**音频驱动 (Audio Driven)** 模式，支持用户上传音频文件（解说/旁白），系统将自动进行语音识别生成字幕（或加载用户提供的字幕），并根据音频时长智能匹配视频素材，一键生成高质量短视频。

## ✨ 功能特性

*   **音频驱动**：直接上传 MP3/WAV/M4A 音频文件作为主轨道，视频时长自动适配音频。
*   **自动字幕 (FunASR)**：内置阿里达摩院 FunASR 模型，若未上传字幕文件，可自动识别语音生成高精度 SRT 字幕。
*   **智能混剪**：根据音频时长，自动从多个视频素材文件夹中随机抽取片段进行填充。
*   **灵活编排**：自定义素材文件夹的**播放顺序**和**时长权重**（百分比），精准控制视频节奏。
*   **字幕自定义**：支持上传现成的 SRT 字幕文件，系统支持字幕样式调整及时间轴自动偏移修正。
*   **背景音乐**：支持自动混音 BGM，可从 `assets/bgm` 目录选择。
*   **批量生成**：支持一次性生成多个不同版本的视频。
*   **多分辨率支持**：
    *   TikTok / Shorts / Reels (1080x1920)
    *   横屏视频 (1920x1080)
    *   自定义分辨率
*   **素材预处理**：内置一键预处理工具，可自动将视频素材调整为指定比例（如 9:16 或 16:9），确保画面统一。
*   **可视化界面**：提供直观的 Streamlit Web 界面 (全中文)，实时预览进度与耗时。

## 📂 目录结构

```text
moviecut/
├── assets/                 # 素材存放目录
│   ├── video/              # 视频素材（请在此创建子文件夹分类存放）
│   └── bgm/                # 背景音乐 (.mp3, .wav)
├── deploy/                 # 部署相关文件
├── output/                 # 视频生成输出目录
├── src/                    # 核心代码库
│   ├── pipeline.py         # 核心处理流程
│   ├── models.py           # 数据模型
│   ├── processors/         # ASR/Matcher/ASR处理器
├── gui_app.py              # Streamlit 启动入口
├── requirements.txt        # 依赖列表
└── README.md               # 项目说明文档
```

## 🛠️ 安装与运行

### 方式一：本地运行 (Local)

1.  **环境准备**：确保已安装 Python 3.10+ 并安装了 FFmpeg（需配置到 PATH）。
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

详见 `deploy` 目录下的说明或直接构建：

```bash
docker build -t autoclip-studio -f deploy/Dockerfile .
docker run -p 8501:8501 -v $(pwd)/assets:/app/assets -v $(pwd)/output:/app/output autoclip-studio
```

## 📖 使用指南

1.  **上传音频**：在界面左侧上传您的解说音频文件 (MP3/WAV)。
2.  **字幕设置**：
    *   (可选) 上传配套的 SRT 字幕文件。
    *   如果不上传，系统将自动使用 **FunASR** 模型进行语音识别生成字幕。
    *   字幕将以“电影级”样式（高对比度、阴影）硬烧录到视频中。
3.  **配置素材**：
    *   **预处理 (推荐)**：若素材尺寸不统一，建议先使用侧边栏的“素材预处理”工具进行统一。
    *   **配置权重**：在界面右侧选择参与混剪的素材文件夹。
    *   **调整权重**：滑动滑块决定该类素材在视频中占据的时长比例。
4.  **全局设置**：在侧边栏设置生成数量、视频分辨率等。
5.  **开始生成**：点击“🎬 开始生成”按钮，观察实时进度和日志。
6.  **预览与导出**：生成完成后，视频将直接在界面展示，文件保存在 `output/YYYYMMDD_HHMMSS_Batch/` 目录。

## ⚠️ 注意事项

*   **FFmpeg**：项目依赖 FFmpeg 进行视频合成及字幕烧录，请确保系统已安装。
*   **FunASR模型**：首次运行时会自动下载 FunASR 相关模型（Paraformer, FSMN, CT-Transformer），请保持网络通畅。
*   **素材要求**：视频素材分辨率若不足 1080p，系统会自动填充或 resize 适配，但建议使用高清素材以获最佳效果。

---
Enjoy creating! 🎥
