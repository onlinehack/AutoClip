import streamlit as st
import os
import json
import time
from src.models import MixConfig, FolderWeight
from src.pipeline import AutoClipPipeline
from src.utils import get_subfolders, get_video_files
from src.config_manager import ConfigManager

def display_metadata(video_path):
    meta_path = video_path.replace('.mp4', '_metadata.json')
    if os.path.exists(meta_path):
        with st.expander("查看原始素材信息 (Source Metadata)", expanded=False):
            try:
                with open(meta_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # Format the data nicely
                for chunk in data:
                    t_start = chunk.get('timeline_start', 0)
                    t_end = chunk.get('timeline_end', 0)
                    st.markdown(f"**时间段: {t_start:.1f}s - {t_end:.1f}s**")
                    
                    segments = chunk.get('segments', [])
                    for seg in segments:
                        src = os.path.basename(seg.get('source_file', 'Unknown'))
                        s_start = seg.get('source_start', 0)
                        s_end = seg.get('source_end', 0)
                        st.text(f"  └─ 来源: {src} [{s_start:.1f}s - {s_end:.1f}s]")
                        
            except Exception as e:
                st.error(f"无法读取元数据: {e}")

st.set_page_config(page_title="AutoClip Studio", layout="wide")

# --- Load Configuration ---
cm = ConfigManager()
config = cm.load_config()

st.title("🚀 AutoClip 智能混剪 (音频驱动)")

# Assets Path
ASSETS_DIR = os.path.join(os.getcwd(), "assets")
OUTPUT_DIR = os.path.join(os.getcwd(), "output")

# Sidebar / Config
st.sidebar.header("全局设置")

# Help function to find index for selectbox
def get_index(options, target):
    try:
        if target in options:
            return options.index(target)
        return 0
    except ValueError:
        return 0

batch_count = st.sidebar.number_input(
    "生成视频数量", 
    min_value=1, 
    value=config.get("batch_count", 1),
    key="batch_count"
)

output_tag = st.sidebar.text_input(
    "输出文件夹标签 (可选)", 
    value=config.get("output_tag", ""),
    help="生成的文件夹名将以此作为前缀",
    key="output_tag"
)

st.sidebar.subheader("视频分辨率")
res_options = ["抖音 / Reels (1080x1920)", "Shorts (1080x1920)", "自定义"]
res_option = st.sidebar.selectbox(
    "选择分辨率",
    res_options,
    index=get_index(res_options, config.get("res_option")),
    key="res_option"
)

if res_option == "自定义":
    vid_width = st.sidebar.number_input("宽度", min_value=100, value=config.get("custom_width", 1080), step=10, key="custom_width")
    vid_height = st.sidebar.number_input("高度", min_value=100, value=config.get("custom_height", 1920), step=10, key="custom_height")
elif "横屏" in res_option:
    vid_width, vid_height = 1920, 1080
else:
    # TikTok / Shorts default
    vid_width, vid_height = 1080, 1920

st.sidebar.divider()
st.sidebar.header("🛠️ 素材预处理 (工具)")
prep_ratio_options = ["抖音 (9:16)", "Youtube (16:9)", "自定义"]
prep_ratio = st.sidebar.selectbox(
    "预处理目标比例",
    prep_ratio_options,
    index=get_index(prep_ratio_options, config.get("prep_ratio")),
    key="prep_ratio"
)

prep_w, prep_h = 1080, 1920
if prep_ratio == "自定义":
    prep_w = st.sidebar.number_input("宽", min_value=100, value=config.get("prep_custom_w", 1080), step=10, key="prep_custom_w")
    prep_h = st.sidebar.number_input("高", min_value=100, value=config.get("prep_custom_h", 1920), step=10, key="prep_custom_h")
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
        count, msg = preprocess_videos(ASSETS_DIR, (prep_w, prep_h), on_prep_progress)
        st.sidebar.success(f"完成! 共处理 {count} 个文件")
        time.sleep(1)
        status_text.empty()
        status_bar.empty()
    except Exception as e:
        st.sidebar.error(f"出错: {e}")

st.sidebar.divider()

# --- Save Configuration Button ---
if st.sidebar.button("💾 保存当前配置"):
    st.session_state['save_config_requested'] = True

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
    
    bgm_options = ["无 (None)"] + bgm_files
    bgm_selected = st.selectbox(
        "背景音乐 (可选)", 
        bgm_options,
        index=get_index(bgm_options, config.get("bgm_selected")),
        key="bgm_selected"
    )

    with st.expander("字幕样式配置 (高级)"):
        sub_font_name = st.text_input("字体名称", value=config.get("sub_font_name", "Noto Sans CJK SC"), key="sub_font_name")
        c1, c2 = st.columns(2)
        with c1:
            sub_font_size = st.number_input("字体大小", value=config.get("sub_font_size", 9), min_value=1, key="sub_font_size")
            sub_outline = st.number_input("描边宽度", value=config.get("sub_outline", 1), min_value=0, key="sub_outline")
            sub_bold = st.checkbox("粗体", value=config.get("sub_bold", True), key="sub_bold")
        with c2:
            sub_color = st.color_picker("字体颜色", value=config.get("sub_color", "#FFFFFF"), key="sub_color")
            sub_shadow = st.number_input("阴影深度", value=config.get("sub_shadow", 1), min_value=0, key="sub_shadow")
            sub_margin_v = st.number_input("垂直边距 (MarginV)", value=config.get("sub_margin_v", 15), min_value=0, key="sub_margin_v")

with col2:
    st.subheader("2. 视觉素材与权重")
    st.info("💡 顺序决定时间线流程。权重决定时长占比。")
    
    video_root = os.path.join(ASSETS_DIR, "video")
    subfolders = [
        f for f in get_subfolders(video_root) 
        if get_video_files(os.path.join(video_root, f))
    ]
    
    folder_weights = []
    current_weights_map = {} # To store for saving

    if not subfolders:
        st.warning(f"{video_root} 未找到子文件夹。请添加视频素材。")
    else:
        # Resolve Defaults for Multiselect
        loaded_ordered = config.get("ordered_folders", [])
        # Filter to keep only existing ones
        valid_defaults = [f for f in loaded_ordered if f in subfolders]
        
        if not valid_defaults and not loaded_ordered:
            valid_defaults = subfolders
        
        selected_ordered_subfolders = st.multiselect(
            "选择并排序视频素材文件夹", 
            options=subfolders,
            default=valid_defaults,
            key="ordered_folders_multiselect"
        )

        if not selected_ordered_subfolders:
             st.warning("请至少选择一个文件夹。")
        else:
            ordered_weights_list = [] # Store tuples (folder, weight)
            saved_weights = config.get("folder_weights", {})

            for folder in selected_ordered_subfolders:
                key = f"w_{folder}"
                # Get saved weight or default 50
                default_val = saved_weights.get(folder, 50)
                
                val = st.slider(f"{folder}", 0, 100, default_val, key=key)
                ordered_weights_list.append((folder, val))
                current_weights_map[folder] = val
                
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
        # Config (Runtime)
        mix_config = MixConfig(
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
            subtitle_bold=sub_bold,
            output_tag=output_tag
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
            results = pipeline.run(mix_config, progress_callback=update_progress)
            total_duration = time.time() - start_ts
            st.success(f"成功生成 {len(results)} 个视频，耗时 {total_duration:.2f} 秒！")
            timer_text.empty() # Clear running timer
            
            st.write("---")
            for i in range(0, len(results), 2):
                cols = st.columns(2)
                with cols[0]:
                    st.write(f"**输出文件:** `{os.path.basename(results[i])}`")
                    st.video(results[i])
                    display_metadata(results[i])
                
                if i + 1 < len(results):
                    with cols[1]:
                        st.write(f"**输出文件:** `{os.path.basename(results[i+1])}`")
                        st.video(results[i+1])
                        display_metadata(results[i+1])

        except Exception as e:
            st.error(f"错误: {str(e)}")
            st.exception(e)

# --- Handle Configuration Saving ---
if st.session_state.get('save_config_requested'):
    # Reset flag
    st.session_state['save_config_requested'] = False
    
    # Construct config object to save
    new_config = {
        "batch_count": st.session_state.get("batch_count", 1),
        "res_option": st.session_state.get("res_option", ""),
        "custom_width": st.session_state.get("custom_width", 1080),
        "custom_height": st.session_state.get("custom_height", 1920),
        "prep_ratio": st.session_state.get("prep_ratio", ""),
        "prep_custom_w": st.session_state.get("prep_custom_w", 1080),
        "prep_custom_h": st.session_state.get("prep_custom_h", 1920),
        "bgm_selected": st.session_state.get("bgm_selected"),
        "output_tag": st.session_state.get("output_tag", ""),
        # Subtitles
        "sub_font_name": st.session_state.get("sub_font_name"),
        "sub_font_size": st.session_state.get("sub_font_size"),
        "sub_outline": st.session_state.get("sub_outline"),
        "sub_bold": st.session_state.get("sub_bold"),
        "sub_color": st.session_state.get("sub_color"),
        "sub_shadow": st.session_state.get("sub_shadow"),
        "sub_margin_v": st.session_state.get("sub_margin_v"),
        # Folders
        "ordered_folders": st.session_state.get("ordered_folders_multiselect", []),
        "folder_weights": current_weights_map
    }
    
    if cm.save_config(new_config):
        st.sidebar.success("✅ 配置已保存到 user_config.json")
    else:
        st.sidebar.error("❌ 配置保存失败")
