import streamlit as st
import os
from src.models import MixConfig, FolderWeight
from src.pipeline import AutoClipPipeline
from src.utils import get_subfolders

st.set_page_config(page_title="AutoClip Studio", layout="wide")

st.title("🚀 AutoClip Studio")

# Sidebar / Config
st.sidebar.header("全局设置")
batch_count = st.sidebar.number_input("生成数量", min_value=1, value=1)
voice = st.sidebar.selectbox("语音角色", ["zh-CN-XiaoxiaoNeural", "zh-CN-YunxiNeural", "en-US-AriaNeural"])

st.sidebar.subheader("分辨率设置")
res_option = st.sidebar.selectbox(
    "选择分辨率",
    ["TikTok / Reels (1080x1920)", "Shorts (1080x1920)", "Horizontal (1920x1080)", "Custom"]
)

if res_option == "Custom":
    vid_width = st.sidebar.number_input("宽度", min_value=100, value=1080, step=10)
    vid_height = st.sidebar.number_input("高度", min_value=100, value=1920, step=10)
elif "Horizontal" in res_option:
    vid_width, vid_height = 1920, 1080
else:
    # TikTok / Shorts default
    vid_width, vid_height = 1080, 1920

# Assets Path
ASSETS_DIR = os.path.join(os.getcwd(), "assets")
OUTPUT_DIR = os.path.join(os.getcwd(), "output")

# Main Area
col1, col2 = st.columns([1, 1])

with col1:
    st.subheader("1. 脚本与音频")
    text_input = st.text_area("在此输入您的脚本...", height=300, value="这是一个测试文案。\nAutoClip 可以自动帮你剪辑视频。\n非常方便！")
    
    bgm_files = []
    bgm_dir = os.path.join(ASSETS_DIR, "bgm")
    if os.path.exists(bgm_dir):
        bgm_files = [f for f in os.listdir(bgm_dir) if f.endswith(('.mp3', '.wav'))]
    
    bgm_selected = st.selectbox("选择背景音乐", ["None"] + bgm_files)

with col2:
    st.subheader("2. 素材顺序与权重 配置")
    st.info("💡 拖动调整顺序（上=前，下=后）。权重决定时长比例。")
    
    video_root = os.path.join(ASSETS_DIR, "video")
    subfolders = get_subfolders(video_root)
    
    folder_weights = []
    if not subfolders:
        st.warning(f"在 {video_root} 未找到子文件夹，请添加视频素材文件夹。")
    else:
        # User defined order
        selected_ordered_subfolders = st.multiselect(
            "选择并排序素材文件夹 (按顺序播放)", 
            options=subfolders,
            default=subfolders
        )

        if not selected_ordered_subfolders:
             st.warning("请至少选择一个文件夹。")
        else:
            # 1. Collect inputs
            temp_weights = {} # Use dict to store temporarily but we need ordered list for Config
            ordered_weights_list = [] # Store tuples (folder, weight)

            for folder in selected_ordered_subfolders:
                # Default key for slider
                key = f"w_{folder}"
                default_val = 50
                val = st.slider(f"{folder}", 0, 100, default_val, key=key)
                ordered_weights_list.append((folder, val))
                
            # 2. Calculate and show percentages (in order)
            total_w = sum(w for _, w in ordered_weights_list)
            
            if total_w > 0:
                st.write("**当前时间线分布 (按顺序):**")
                for f, w in ordered_weights_list:
                    pct = (w / total_w) * 100
                    st.write(f"- **{f}**: {pct:.1f}%")
                    folder_weights.append(FolderWeight(folder=f, weight=w))
            else:
                st.error("总权重必须大于 0")

st.divider()

# Action Logic
if st.button("🎬 开始生成", type="primary"):
    if not text_input.strip():
        st.error("请输入文案。")
    elif not folder_weights or sum(fw.weight for fw in folder_weights) == 0:
        st.error("至少有一个文件夹的权重必须大于 0。")
    else:
        # Config
        config = MixConfig(
            text=text_input,
            voice=voice,
            folder_weights=folder_weights,
            batch_count=batch_count,
            bgm_file=None if bgm_selected == "None" else bgm_selected,
            width=vid_width,
            height=vid_height
        )
        
        # Run Pipeline
        pipeline = AutoClipPipeline(ASSETS_DIR, OUTPUT_DIR)
        
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        def update_progress(p, msg):
            progress_bar.progress(p)
            status_text.text(msg)
            
        try:
            results = pipeline.run(config, progress_callback=update_progress)
            st.success(f"成功生成 {len(results)} 个视频！")
            
            # Display Logic: Grid Layout (2 columns per row)
            st.write("---")
            for i in range(0, len(results), 2):
                cols = st.columns(2)
                # First video
                with cols[0]:
                    st.write(f"**输出:** `{os.path.basename(results[i])}`")
                    st.video(results[i])
                
                # Second video if exists
                if i + 1 < len(results):
                    with cols[1]:
                        st.write(f"**输出:** `{os.path.basename(results[i+1])}`")
                        st.video(results[i+1])

        except Exception as e:
            st.error(f"错误: {str(e)}")
            # st.exception(e) # Uncomment for debug
