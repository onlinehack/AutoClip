import streamlit as st
import os
from src.models import MixConfig, FolderWeight
from src.pipeline import AutoClipPipeline
from src.utils import get_subfolders

st.set_page_config(page_title="AutoClip Studio", layout="wide")

st.title("🚀 AutoClip Studio (Audio Driven)")

# Assets Path
ASSETS_DIR = os.path.join(os.getcwd(), "assets")
OUTPUT_DIR = os.path.join(os.getcwd(), "output")

# Sidebar / Config
st.sidebar.header("Global Settings")
batch_count = st.sidebar.number_input("Generate Count", min_value=1, value=1)

st.sidebar.subheader("Resolution")
res_option = st.sidebar.selectbox(
    "Select Resolution",
    ["TikTok / Reels (1080x1920)", "Shorts (1080x1920)", "Horizontal (1920x1080)", "Custom"]
)

if res_option == "Custom":
    vid_width = st.sidebar.number_input("Width", min_value=100, value=1080, step=10)
    vid_height = st.sidebar.number_input("Height", min_value=100, value=1920, step=10)
elif "Horizontal" in res_option:
    vid_width, vid_height = 1920, 1080
else:
    # TikTok / Shorts default
    vid_width, vid_height = 1080, 1920

# Main Area
col1, col2 = st.columns([1, 1])

with col1:
    st.subheader("1. Audio & Subtitles")
    
    # Ensure temp dir exists
    TEMP_UPLOAD_DIR = os.path.join(os.getcwd(), "temp_uploads")
    os.makedirs(TEMP_UPLOAD_DIR, exist_ok=True)
    
    uploaded_audio = st.file_uploader("Upload Audio (Required)", type=['mp3', 'wav', 'm4a'])
    uploaded_srt = st.file_uploader("Upload SRT (Optional)", type=['srt'])
    
    audio_path_str = ""
    srt_path_str = None
    
    if uploaded_audio:
        # Save to temp
        audio_path_str = os.path.join(TEMP_UPLOAD_DIR, uploaded_audio.name)
        with open(audio_path_str, "wb") as f:
            f.write(uploaded_audio.getbuffer())
        st.success(f"Loaded: {uploaded_audio.name}")
            
    if uploaded_srt:
        srt_path_str = os.path.join(TEMP_UPLOAD_DIR, uploaded_srt.name)
        with open(srt_path_str, "wb") as f:
            f.write(uploaded_srt.getbuffer())
        st.success(f"Loaded: {uploaded_srt.name}")
    else:
        st.info("No SRT uploaded. Will auto-generate using FunASR.")

    bgm_files = []
    bgm_dir = os.path.join(ASSETS_DIR, "bgm")
    if os.path.exists(bgm_dir):
        bgm_files = [f for f in os.listdir(bgm_dir) if f.endswith(('.mp3', '.wav'))]
    
    bgm_selected = st.selectbox("Background Music (Optional)", ["None"] + bgm_files)

with col2:
    st.subheader("2. Visual Material & Weights")
    st.info("💡 Order determines timeline flow. Weight determines duration share.")
    
    video_root = os.path.join(ASSETS_DIR, "video")
    subfolders = get_subfolders(video_root)
    
    folder_weights = []
    if not subfolders:
        st.warning(f"No subfolders found in {video_root}. Please add video assets.")
    else:
        # User defined order
        selected_ordered_subfolders = st.multiselect(
            "Select and Order Video Folders", 
            options=subfolders,
            default=subfolders
        )

        if not selected_ordered_subfolders:
             st.warning("Please select at least one folder.")
        else:
            ordered_weights_list = [] # Store tuples (folder, weight)

            for folder in selected_ordered_subfolders:
                key = f"w_{folder}"
                default_val = 50
                val = st.slider(f"{folder}", 0, 100, default_val, key=key)
                ordered_weights_list.append((folder, val))
                
            total_w = sum(w for _, w in ordered_weights_list)
            
            if total_w > 0:
                st.write("**Timeline Distribution:**")
                for f, w in ordered_weights_list:
                    pct = (w / total_w) * 100
                    st.write(f"- **{f}**: {pct:.1f}%")
                    folder_weights.append(FolderWeight(folder=f, weight=w))
            else:
                st.error("Total weight must be > 0")

st.divider()

# Action Logic
if st.button("🎬 Start Generation", type="primary"):
    if not uploaded_audio:
        st.error("Please upload an audio file.")
    elif not folder_weights:
        st.error("Please configure folder weights.")
    else:
        # Config
        config = MixConfig(
            audio_path=audio_path_str,
            srt_path=srt_path_str,
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
            st.success(f"Successfully generated {len(results)} videos!")
            
            st.write("---")
            for i in range(0, len(results), 2):
                cols = st.columns(2)
                with cols[0]:
                    st.write(f"**Output:** `{os.path.basename(results[i])}`")
                    st.video(results[i])
                
                if i + 1 < len(results):
                    with cols[1]:
                        st.write(f"**Output:** `{os.path.basename(results[i+1])}`")
                        st.video(results[i+1])

        except Exception as e:
            st.error(f"Error: {str(e)}")
            st.exception(e) 
