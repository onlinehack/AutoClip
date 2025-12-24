import streamlit as st
import os
import time
from src.models import MixConfig, FolderWeight
from src.pipeline import AutoClipPipeline
from src.utils import get_subfolders, get_video_files

st.set_page_config(page_title="AutoClip Studio", layout="wide")

st.title("🚀 AutoClip 智能混剪 (音频驱动)")

# Assets Path
ASSETS_DIR = os.path.join(os.getcwd(), "assets")
OUTPUT_DIR = os.path.join(os.getcwd(), "output")

# Sidebar / Config
st.sidebar.header("全局设置")
batch_count = st.sidebar.number_input("生成视频数量", min_value=1, value=1)

st.sidebar.subheader("视频分辨率")
res_option = st.sidebar.selectbox(
    "选择分辨率",
    ["抖音 / Reels (1080x1920)", "Shorts (1080x1920)"]
)

if res_option == "自定义":
    vid_width = st.sidebar.number_input("宽度", min_value=100, value=1080, step=10)
    vid_height = st.sidebar.number_input("高度", min_value=100, value=1920, step=10)
elif "横屏" in res_option:
    vid_width, vid_height = 1920, 1080
else:
    # TikTok / Shorts default
    vid_width, vid_height = 1080, 1920

st.sidebar.divider()
st.sidebar.header("🛠️ 素材预处理 (工具)")
prep_ratio = st.sidebar.selectbox(
    "预处理目标比例",
    ["抖音 (9:16)", "Youtube (16:9)", "自定义"],
    index=0,
    key="prep_ratio_select"
)

prep_w, prep_h = 1080, 1920
if prep_ratio == "自定义":
    prep_w = st.sidebar.number_input("宽", min_value=100, value=1080, step=10, key="prep_w")
    prep_h = st.sidebar.number_input("高", min_value=100, value=1920, step=10, key="prep_h")
elif "16:9" in prep_ratio:
    prep_w, prep_h = 1920, 1080
else:
    # 9:16
    prep_w, prep_h = 1080, 1920

if st.sidebar.button("⚙️ 一键预处理素材"):
    from src.preprocessor import preprocess_videos
    
    status_bar = st.sidebar.progress(0)
    status_text = st.sidebar.empty()
    
    def on_prep_progress(p, msg):
        status_bar.progress(p)
        status_text.text(msg)
        
    try:
        # ASSETS_DIR is defined above in the file (line 13)
        count, msg = preprocess_videos(ASSETS_DIR, (prep_w, prep_h), on_prep_progress)
        st.sidebar.success(f"完成! 共处理 {count} 个文件")
        time.sleep(1)
        status_text.empty()
        status_bar.empty()
    except Exception as e:
        st.sidebar.error(f"出错: {e}")

# Main Area
col1, col2 = st.columns([1, 1])

with col1:
    st.subheader("1. 音频与字幕")
    
    # Ensure temp dir exists
    TEMP_UPLOAD_DIR = os.path.join(os.getcwd(), "temp_uploads")
    os.makedirs(TEMP_UPLOAD_DIR, exist_ok=True)
    
    uploaded_audio = st.file_uploader("上传音频 (必选)", type=['mp3', 'wav', 'm4a'])
    uploaded_srt = st.file_uploader("上传 SRT 字幕 (可选)", type=['srt'])
    
    audio_path_str = ""
    srt_path_str = None
    
    if uploaded_audio:
        # Save to temp
        audio_path_str = os.path.join(TEMP_UPLOAD_DIR, uploaded_audio.name)
        with open(audio_path_str, "wb") as f:
            f.write(uploaded_audio.getbuffer())
        st.success(f"已加载: {uploaded_audio.name}")
            
    if uploaded_srt:
        srt_path_str = os.path.join(TEMP_UPLOAD_DIR, uploaded_srt.name)
        with open(srt_path_str, "wb") as f:
            f.write(uploaded_srt.getbuffer())
        st.success(f"已加载: {uploaded_srt.name}")
    else:
        st.info("未上传字幕。将使用 FunASR 自动生成。")

    bgm_files = []
    bgm_dir = os.path.join(ASSETS_DIR, "bgm")
    if os.path.exists(bgm_dir):
        bgm_files = [f for f in os.listdir(bgm_dir) if f.endswith(('.mp3', '.wav'))]
    
    bgm_selected = st.selectbox("背景音乐 (可选)", ["无 (None)"] + bgm_files)

    with st.expander("字幕样式配置 (高级)"):
        sub_font_name = st.text_input("字体名称", value="Noto Sans CJK SC")
        c1, c2 = st.columns(2)
        with c1:
            sub_font_size = st.number_input("字体大小", value=9, min_value=1)
            sub_outline = st.number_input("描边宽度", value=1, min_value=0)
            sub_bold = st.checkbox("粗体", value=True)
        with c2:
            sub_color = st.color_picker("字体颜色", value="#FFFFFF")
            sub_shadow = st.number_input("阴影深度", value=1, min_value=0)
            sub_margin_v = st.number_input("垂直边距 (MarginV)", value=15, min_value=0)

with col2:
    st.subheader("2. 视觉素材与权重")
    st.info("💡 顺序决定时间线流程。权重决定时长占比。")
    
    video_root = os.path.join(ASSETS_DIR, "video")
    subfolders = [
        f for f in get_subfolders(video_root) 
        if get_video_files(os.path.join(video_root, f))
    ]
    
    folder_weights = []
    if not subfolders:
        st.warning(f"{video_root} 未找到子文件夹。请添加视频素材。")
    else:
        # User defined order
        selected_ordered_subfolders = st.multiselect(
            "选择并排序视频素材文件夹", 
            options=subfolders,
            default=subfolders
        )

        if not selected_ordered_subfolders:
             st.warning("请至少选择一个文件夹。")
        else:
            ordered_weights_list = [] # Store tuples (folder, weight)

            for folder in selected_ordered_subfolders:
                key = f"w_{folder}"
                default_val = 50
                val = st.slider(f"{folder}", 0, 100, default_val, key=key)
                ordered_weights_list.append((folder, val))
                
            total_w = sum(w for _, w in ordered_weights_list)
            
            if total_w > 0:
                st.write("**时间线分布:**")
                for f, w in ordered_weights_list:
                    pct = (w / total_w) * 100
                    st.write(f"- **{f}**: {pct:.1f}%")
                    folder_weights.append(FolderWeight(folder=f, weight=w))
            else:
                st.error("总权重必须大于 0")

st.divider()

# Action Logic
if st.button("🎬 开始生成", type="primary"):
    if not uploaded_audio:
        st.error("请上传音频文件。")
    elif not folder_weights:
        st.error("请配置文件夹权重。")
    else:
        # Config
        config = MixConfig(
            audio_path=audio_path_str,
            srt_path=srt_path_str,
            folder_weights=folder_weights,
            batch_count=batch_count,
            bgm_file=None if bgm_selected == "无 (None)" else bgm_selected,
            width=vid_width,
            height=vid_height,
            subtitle_font_name=sub_font_name,
            subtitle_font_size=sub_font_size,
            subtitle_color=sub_color,
            subtitle_outline=sub_outline,
            subtitle_shadow=sub_shadow,
            subtitle_margin_v=sub_margin_v,
            subtitle_bold=sub_bold
        )
        
        # Run Pipeline
        pipeline = AutoClipPipeline(ASSETS_DIR, OUTPUT_DIR)
        
        progress_bar = st.progress(0)
        status_text = st.empty()
        timer_text = st.empty()
        
        start_ts = time.time()
        
        def update_progress(p, msg):
            progress_bar.progress(p)
            status_text.text(msg)
            elapsed = time.time() - start_ts
            timer_text.info(f"⏱️ 已耗时: {elapsed:.1f}s")
            
        try:
            results = pipeline.run(config, progress_callback=update_progress)
            total_duration = time.time() - start_ts
            st.success(f"成功生成 {len(results)} 个视频，耗时 {total_duration:.2f} 秒！")
            timer_text.empty() # Clear running timer
            
            st.write("---")
            for i in range(0, len(results), 2):
                cols = st.columns(2)
                with cols[0]:
                    st.write(f"**输出文件:** `{os.path.basename(results[i])}`")
                    st.video(results[i])
                
                if i + 1 < len(results):
                    with cols[1]:
                        st.write(f"**输出文件:** `{os.path.basename(results[i+1])}`")
                        st.video(results[i+1])

        except Exception as e:
            st.error(f"错误: {str(e)}")
            st.exception(e) 
