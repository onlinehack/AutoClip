import streamlit as st
import os
import json
import time
import pandas as pd
from datetime import datetime
from src.models import MixConfig, FolderWeight
from src.pipeline import AutoClipPipeline
from src.utils import get_subfolders, get_video_files
from src.config_manager import ConfigManager
from pathlib import Path
from src.preprocess import process_video, get_video_files as get_all_video_files

# --- Helper Functions ---
def display_metadata(video_path):
    meta_path = video_path.replace('.mp4', '_metadata.json')
    if os.path.exists(meta_path):
        with st.expander("查看原始素材信息 (Source Metadata)", expanded=False):
            try:
                with open(meta_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                for chunk in data:
                    t_start = chunk.get('timeline_start', 0)
                    t_end = chunk.get('timeline_end', 0)
                    speed = chunk.get('speed_factor', 1.0)
                    st.markdown(f"**时间段: {t_start:.1f}s - {t_end:.1f}s (Speed: {speed}x)**")
                    
                    segments = chunk.get('segments', [])
                    for seg in segments:
                        src = os.path.basename(seg.get('source_file', 'Unknown'))
                        s_start = seg.get('source_start', 0)
                        s_end = seg.get('source_end', 0)
                        st.text(f"  └─ 来源: {src} [{s_start:.1f}s - {s_end:.1f}s]")
                        
            except Exception as e:
                st.error(f"无法读取元数据: {e}")

def get_index(options, target):
    try:
        if target in options:
            return options.index(target)
        return 0
    except ValueError:
        return 0

def render_queue_dataframe(placeholder):
    if not st.session_state['task_queue']:
        placeholder.write("队列为空 (Empty Queue)")
    else:
        queue_display = []
        for t in st.session_state['task_queue']:
            queue_display.append({
                "ID": t["id"],
                "音频": t["audio_name"],
                "字幕": t["srt_name"],
                "转场": f"{t['trans_type'].split(' ')[0]} ({t['trans_dur']}s)" if "无" not in t['trans_type'] else "无",
                "数量": t["count"],
                "状态": t["status"]
            })
        placeholder.dataframe(pd.DataFrame(queue_display), hide_index=True)

# --- Page Setup ---
st.set_page_config(page_title="AutoClip Studio", layout="wide")

# --- State Initialization ---
if 'task_queue' not in st.session_state:
    st.session_state['task_queue'] = []
if 'uploader_key' not in st.session_state:
    st.session_state['uploader_key'] = 0
if 'save_config_requested' not in st.session_state:
    st.session_state['save_config_requested'] = False

# --- Load Configuration ---
cm = ConfigManager()
config = cm.load_config()

# Directories
ASSETS_DIR = os.path.join(os.getcwd(), "assets")
OUTPUT_DIR = os.path.join(os.getcwd(), "output")
TEMP_UPLOAD_DIR = os.path.join(os.getcwd(), "temp_uploads")
os.makedirs(TEMP_UPLOAD_DIR, exist_ok=True)

st.title("🚀 AutoClip 智能混剪 (Task Queue Mode)")

# --- Sidebar: Global Configuration ---
st.sidebar.header("全局设置 (Global Settings)")

output_tag = st.sidebar.text_input(
    "输出文件夹标签 (前缀)", 
    value=config.get("output_tag", ""),
    help="所有任务生成的文件夹名将以此作为前缀",
    key="output_tag"
)

# Resolution
st.sidebar.subheader("视频分辨率")
res_options = ["抖音 / Reels (1080x1920)", "Shorts (1080x1920)", "自定义"]
res_option = st.sidebar.selectbox(
    "选择分辨率", res_options,
    index=get_index(res_options, config.get("res_option")),
    key="res_option"
)

if res_option == "自定义":
    vid_width = st.sidebar.number_input("宽度", min_value=100, value=config.get("custom_width", 1080), key="custom_width")
    vid_height = st.sidebar.number_input("高度", min_value=100, value=config.get("custom_height", 1920), key="custom_height")
elif "横屏" in res_option:
    vid_width, vid_height = 1920, 1080
else:
    vid_width, vid_height = 1080, 1920

# Audio/Subtitle Style
st.sidebar.divider()
bgm_files = []
bgm_dir = os.path.join(ASSETS_DIR, "bgm")
if os.path.exists(bgm_dir):
    bgm_files = [f for f in os.listdir(bgm_dir) if f.endswith(('.mp3', '.wav'))]

bgm_options = ["无 (None)"] + bgm_files
bgm_selected = st.sidebar.selectbox(
    "背景音乐 (BGM)", 
    bgm_options,
    index=get_index(bgm_options, config.get("bgm_selected")),
    key="bgm_selected"
)

with st.sidebar.expander("字幕样式配置"):
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

# Video Source Weights
st.sidebar.divider()
st.sidebar.subheader("视觉素材权重 (Global)")
video_root = os.path.join(ASSETS_DIR, "video")
subfolders = [f for f in get_subfolders(video_root) if get_video_files(os.path.join(video_root, f))]
folder_weights = []
current_weights_map = {}

if not subfolders:
    st.sidebar.warning("未找到素材文件夹。")
else:
    loaded_ordered = config.get("ordered_folders", [])
    valid_defaults = [f for f in loaded_ordered if f in subfolders] or subfolders
    
    selected_ordered_subfolders = st.sidebar.multiselect(
        "启用素材文件夹", options=subfolders, default=valid_defaults, key="ordered_folders_multiselect"
    )
    
    saved_weights = config.get("folder_weights", {})
    # saved_weights format in config might be simple dict {folder: weight} OR newer {folder: {weight: x, speed: y}}
    # We need to handle backward compatibility.
    
    for folder in selected_ordered_subfolders:
         # Extract saved values safely
         fw_data = saved_weights.get(folder, 50)
         if isinstance(fw_data, dict):
             val_w = fw_data.get("weight", 50)
             val_s = fw_data.get("speed", 1.0)
         else:
             val_w = fw_data if isinstance(fw_data, int) else 50
             val_s = 1.0

         c1, c2 = st.sidebar.columns([3, 1])
         with c1:
            val = st.slider(f"{folder}", 0, 100, val_w, key=f"w_{folder}", help=f"{folder} 权重")
         with c2:
            spd = st.number_input("x", 0.1, 10.0, float(val_s), 0.1, key=f"s_{folder}", help=f"{folder} 播放倍数")
         
         # Save structure for Config Manager (Complex Dict)
         current_weights_map[folder] = {"weight": val, "speed": spd}
         
         # Construct Object for Pipeline
         folder_weights.append(FolderWeight(folder=folder, weight=val, speed=spd))

if st.sidebar.button("💾 保存配置 (Save Config)"):
    st.session_state['save_config_requested'] = True

# --- Preprocessing Tool ---
st.sidebar.divider()
st.sidebar.header("🛠️ 素材预处理工具")
with st.sidebar.expander("一键格式化 (Pre-process)", expanded=False):
    st.info("自动将 assets/video 下的视频裁剪为指定比例。")
    
    pp_mode = st.radio("目标分辨率", ["竖屏 (1080x1920)", "横屏 (1920x1080)", "自定义"], key="pp_mode")
    
    if pp_mode == "自定义":
        pp_w = st.number_input("宽 (Width)", value=1080, key="pp_cw")
        pp_h = st.number_input("高 (Height)", value=1920, key="pp_ch")
    elif "横屏" in pp_mode:
        pp_w, pp_h = 1920, 1080
    else:
        pp_w, pp_h = 1080, 1920
    
    overwrite_src = st.checkbox("⚠️ 覆盖原文件 (Overwrite)", value=True, help="警告：处理成功后将直接替换原始文件，操作不可逆！")
        
    if st.button("🚀 开始处理"):
        src_dir = os.path.join(ASSETS_DIR, "video")
        
        if not os.path.exists(src_dir):
            st.error(f"源文件夹不存在: {src_dir}")
        else:
            files_to_proc = get_all_video_files(src_dir)
            if not files_to_proc:
                st.warning("源文件夹中没有视频文件。")
            else:
                pp_prog = st.progress(0)
                pp_status = st.empty()
                
                # Check overwrite mode
                if overwrite_src:
                     st.warning("模式: ⚠️ 覆盖原文件")
                else: 
                     dst_dir = os.path.join(ASSETS_DIR, "video_optimized")
                     st.info(f"模式: 输出到 {dst_dir}")

                success_count = 0
                # Prepare tasks list
                tasks = []
                
                # Logic to prepare tasks
                for fpath in files_to_proc:
                    if overwrite_src:
                        out_path = fpath + ".tmp.mp4" # Temp file for overwrite
                    else:
                        rel_path = os.path.relpath(fpath, src_dir)
                        out_path_full = os.path.join(dst_dir, rel_path)
                        out_path = str(Path(out_path_full).with_suffix('.mp4'))
                        
                        # Skip if exists and not overwrite (simple check before safe process)
                        if os.path.exists(out_path):
                            continue
                            
                    tasks.append((fpath, out_path, pp_w, pp_h))
                
                if not tasks:
                    st.info("所有文件已存在或无需处理。")
                else:
                    from src.preprocess import batch_process_parallel
                    
                    # Use 50% of cores by default for GUI
                    max_workers = max(1, os.cpu_count() // 2)
                    st.write(f"正在使用 {max_workers} 个并行进程处理...")

                    def update_progress(curr, total):
                        pp_prog.progress(curr / total)
                        pp_status.text(f"Processing... {curr}/{total}")

                    results = batch_process_parallel(tasks, max_workers=max_workers, progress_callback=update_progress)
                    
                    # Post-processing for overwrite mode
                    if overwrite_src:
                        for i, (fpath, tmp_path, _, _) in enumerate(tasks):
                            if results[i]: # If success
                                try:
                                    os.replace(tmp_path, fpath)
                                    success_count += 1
                                except Exception as e:
                                    st.error(f"Replace failed: {e}")
                            else:
                                if os.path.exists(tmp_path):
                                    os.remove(tmp_path)
                    else:
                        success_count = sum(results) + (len(files_to_proc) - len(tasks)) # Add skipped ones
                
                pp_status.success(f"处理完成！成功: {success_count}/{len(files_to_proc)}")

# --- Main Interface ---

col1, col2 = st.columns([1, 1], gap="large")

with col1:
    st.subheader("1. 添加任务 (Add Task)")
    st.info("上传音频和字幕，添加到待处理队列。")
    
    # Dynamic key to reset uploader
    ukey = st.session_state['uploader_key']
    
    with st.form("add_task_form", clear_on_submit=True):
        uploaded_audio = st.file_uploader("音频文件 (必选)", type=['mp3', 'wav', 'm4a'], key=f"audio_{ukey}")
        uploaded_srt = st.file_uploader("字幕文件 (可选, 留空自动生成)", type=['srt'], key=f"srt_{ukey}")
        task_count = st.number_input("生成数量", min_value=1, value=config.get("batch_count", 1), key=f"cnt_{ukey}")
        
        st.markdown("**👉 转场设置 (Transition)**")
        c_t1, c_t2 = st.columns(2)
        with c_t1:
            trans_type = st.selectbox("转场类型", ["无 (Hard Cut)", "叠化 (Crossfade)", "闪黑 (Fade to Black)"], index=0, key=f"tt_{ukey}")
        with c_t2:
            trans_dur = st.number_input("转场时长 (秒)", min_value=0.1, max_value=2.0, value=0.5, step=0.1, key=f"td_{ukey}", disabled=(trans_type=="无 (Hard Cut)"))

        submitted = st.form_submit_button("➕ 添加到队列")
        
        if submitted:
            if not uploaded_audio:
                st.error("必须上传音频文件！")
            else:
                # 1. Save Files
                audio_path = os.path.join(TEMP_UPLOAD_DIR, uploaded_audio.name)
                with open(audio_path, "wb") as f:
                    f.write(uploaded_audio.getbuffer())
                
                srt_path = None
                srt_display = "Auto Check"
                if uploaded_srt:
                    srt_path = os.path.join(TEMP_UPLOAD_DIR, uploaded_srt.name)
                    with open(srt_path, "wb") as f:
                        f.write(uploaded_srt.getbuffer())
                    srt_display = uploaded_srt.name
                
                # 2. Add to Session State
                task_data = {
                    "id": len(st.session_state['task_queue']) + 1,
                    "audio_name": uploaded_audio.name,
                    "audio_path": audio_path,
                    "srt_name": srt_display,
                    "srt_path": srt_path,
                    "count": task_count,
                    "trans_type": trans_type,
                    "trans_dur": trans_dur,
                    "status": "Ready"
                }
                st.session_state['task_queue'].append(task_data)
                
                # 3. Increment Key to reset uploader
                st.session_state['uploader_key'] += 1
                st.success(f"任务已添加: {uploaded_audio.name}")
                st.rerun()

with col2:
    st.subheader("2. 任务队列 (Queue)")
    
    if not st.session_state['task_queue']:
        # Placeholder for empty state or table
        queue_placeholder = st.empty()
        render_queue_dataframe(queue_placeholder)
    else:
        queue_placeholder = st.empty()
        render_queue_dataframe(queue_placeholder)
        
        c_act1, c_act2 = st.columns(2)
        if c_act1.button("🗑️ 清空队列"):
            st.session_state['task_queue'] = []
            st.rerun()
        
        start_btn = c_act2.button("🎬 开始批量生成", type="primary")

# --- Execution Area ---
st.divider()

if 'start_btn' in locals() and start_btn:
    if not folder_weights:
        st.error("错误：未配置视频素材权重。请在侧边栏设置。")
    elif not st.session_state['task_queue']:
        st.error("错误：队列为空。")
    else:
        pipeline = AutoClipPipeline(ASSETS_DIR, OUTPUT_DIR)
        
        main_progress = st.progress(0)
        main_status = st.empty()
        
        total_tasks = len(st.session_state['task_queue'])
        all_results = []
        
        start_time_global = time.time()
        
        for idx, task in enumerate(st.session_state['task_queue']):
            task_id = idx + 1
            main_status.markdown(f"### 正在处理任务 {task_id}/{total_tasks}: {task['audio_name']}")
            
            # Construct Config for this task
            mix_config = MixConfig(
                audio_path=task['audio_path'],
                srt_path=task['srt_path'],
                folder_weights=folder_weights,
                batch_count=task['count'],
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
                output_tag=output_tag,
                # Fix: Extract English key from "中文 (English)" format
                transition_type=task.get('trans_type', "无").split("(")[-1].strip(")") if "(" in task.get('trans_type', "") else "None",
                transition_duration=task.get('trans_dur', 0.5)
            )
            
            # Progress Callback wrapper
            def task_progress(p, msg):
                # Map task progress (0-1) to global progress slot for this task
                global_p = (idx + p) / total_tasks
                main_progress.progress(min(global_p, 1.0))
                # Optional: Show detailed sub-status if needed
            
            try:
                results = pipeline.run(mix_config, progress_callback=task_progress)
                task['status'] = 'Done'
                render_queue_dataframe(queue_placeholder)
                all_results.extend(results)
                st.success(f"任务 {task_id} 完成! 生成 {len(results)} 个视频。")
                
            except Exception as e:
                task['status'] = 'Error'
                render_queue_dataframe(queue_placeholder)
                st.error(f"任务 {task['audio_name']} 失败: {e}")
                
        main_progress.progress(1.0)
        main_status.success(f"✅ 所有任务完成！总耗时: {time.time() - start_time_global:.1f}s")
        
        # Display Results
        st.write("---")
        st.subheader("生成结果预览")
        
        if not all_results:
            st.warning("无视频生成。")
        else:
             for i in range(0, len(all_results), 2):
                cols = st.columns(2)
                with cols[0]:
                    st.write(f"📁 `{os.path.basename(all_results[i])}`")
                    st.video(all_results[i])
                    display_metadata(all_results[i])
                
                if i + 1 < len(all_results):
                    with cols[1]:
                        st.write(f"📁 `{os.path.basename(all_results[i+1])}`")
                        st.video(all_results[i+1])
                        display_metadata(all_results[i+1])

# --- Handle Save Config ---
if st.session_state.get('save_config_requested'):
    st.session_state['save_config_requested'] = False
    new_config = {
        "batch_count": 1, # Default placeholder
        "res_option": res_option,
        "custom_width": vid_width,
        "custom_height": vid_height,
        "bgm_selected": bgm_selected,
        "output_tag": output_tag,
        # Subtitles (Use current session state keys or vars)
        "sub_font_name": sub_font_name,
        "sub_font_size": sub_font_size,
        "sub_outline": sub_outline,
        "sub_bold": sub_bold,
        "sub_color": sub_color,
        "sub_shadow": sub_shadow,
        "sub_margin_v": sub_margin_v,
        # Folders
        "ordered_folders": st.session_state.get("ordered_folders_multiselect", []),
        "folder_weights": current_weights_map
    }
    
    if cm.save_config(new_config):
        st.sidebar.success("✅ 配置已保存!")
    else:
        st.sidebar.error("❌ 配置保存失败")
