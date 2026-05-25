import streamlit as st
import pandas as pd
import pydeck as pdk
from llm_parser import parse_dispatch_intent
from routing_engine import load_local_network, calculate_routes
import os
from dotenv import load_dotenv

# 自动寻找并读取 .env 文件里的变量
load_dotenv() 

# 读取你的密钥 (注意：括号里的名字必须和你在 .env 里写的一模一样)
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
GAODE_API_KEY = os.getenv("GAODE_API_KEY")


# --- 1. 全局配置与纯净 SaaS 样式 ---
st.set_page_config(page_title="智能物流调度工作台", layout="wide", initial_sidebar_state="collapsed")

custom_css = """
<style>
    .block-container {
        padding-top: 3rem !important; 
        padding-bottom: 1rem !important;
        max-width: 100% !important;
    }
    
    /* 消除列内的多余间隙，统一由下面盒子的 margin 控制 */
    [data-testid="stColumn"]:first-of-type > div[data-testid="stVerticalBlock"],
    [data-testid="column"]:first-of-type > div[data-testid="stVerticalBlock"] {
        gap: 1.5rem !important; 
    }

    /* 业务控制中心 SaaS 毛玻璃背景 */
    div[data-testid="stColumn"]:first-of-type > div[data-testid="stVerticalBlock"],
    div[data-testid="column"]:nth-child(1) > div[data-testid="stVerticalBlock"] {
        background-color: rgba(226, 232, 240, 0.45) !important; /* 统一的高级浅灰蓝 */
        backdrop-filter: blur(16px) !important; 
        -webkit-backdrop-filter: blur(16px) !important; 
        border: 1px solid rgba(255, 255, 255, 0.8) !important; 
        box-shadow: 0 8px 32px 0 rgba(31, 38, 135, 0.05) !important;
        border-radius: 16px !important;
        padding: 25px 20px !important; 
    }

    /* 地图样式保持不变 */
    div[data-testid="stDeckGlJsonChart"] {
        height: 82vh !important; 
        border-radius: 16px;
        border: 2px solid #e2e8f0;
        box-shadow: 0 4px 20px rgba(0,0,0,0.06);
        overflow: hidden;
    }
    div[data-testid="stDeckGlJsonChart"] iframe {
        height: 100% !important;
        width: 100% !important;
    }

    /* 聊天气泡样式保持不变 */
    div[data-testid="stChatMessage"] {
        background-color: #f1f5f9;
        border-radius: 8px;
        padding: 14px;
        border: 1px solid #e2e8f0;
        margin-bottom: 8px;
    }
    div[data-testid="stChatMessage"] div.message-bubble { margin: 0px !important; padding: 0px !important; }
    div[data-testid="stChatMessage"] div.avatar-container { display: none !important; }
</style>
"""
st.markdown(custom_css, unsafe_allow_html=True)

st.markdown("<h2 style='margin-top: -20px; margin-bottom: 5px; color: #0f172a; font-weight: 800;'>智能物流调度工作台</h2>", unsafe_allow_html=True)
st.markdown("<p style='font-size: 0.9em; color: #64748b; margin-bottom: 25px;'>基于 DeepSeek V3 构建的全局调度引擎—采用热数据分离架构：高频订单本地缓存和长尾地址高德API动态解析，实现秒级路网熔断与重排线</p>", unsafe_allow_html=True)

# --- 状态初始化 ---
if "business_mode" not in st.session_state:
    st.session_state.business_mode = "1. 订单规划"
if "messages" not in st.session_state:
    st.session_state.messages = []
if "ui_state" not in st.session_state:
    st.session_state.ui_state = "normal" 
if "blocked_road" not in st.session_state:
    st.session_state.blocked_road = None
if "start_point" not in st.session_state:
    st.session_state.start_point = "春熙路 IFS"
if "end_point" not in st.session_state:
    st.session_state.end_point = "天府软件园"
if "prev_order" not in st.session_state:
    st.session_state.prev_order = "ORD-901 (西财光华校区南门)"

# --- 数据加载 ---
try:
    G, nodes_gdf = load_local_network()
except Exception as e:
    st.error(f"路网加载失败: {str(e)}")
    st.stop()


# --- UI 组件渲染函数定义 (必须在 columns 调用前) ---
def render_kpi_card(title, value, is_alert=False):
    color = "#ef4444" if is_alert else "#10b981"
    bg_color = "rgba(254, 226, 226, 0.4)" if is_alert else "rgba(255, 255, 255, 0.5)"
    border_color = "rgba(239, 68, 68, 0.2)" if is_alert else "rgba(255, 255, 255, 0.8)"
    
    st.markdown(f"""
    <div style="background: {bg_color}; backdrop-filter: blur(10px); -webkit-backdrop-filter: blur(10px); padding: 15px; border-radius: 12px; border: 1px solid {border_color}; margin-bottom: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.02);">
        <div style="font-size: 0.85em; color: #475569; font-weight: 600; margin-bottom: 4px;">{title}</div>
        <div style="font-size: 1.15em; font-weight: 800; color: {color};">{value}</div>
    </div>
    """, unsafe_allow_html=True)


# --- 核心布局划分 ---
col_left, col_mid, col_right = st.columns([2, 3, 5], gap="large")

# ==================== 左侧：控制台 (分块设计) ====================
with col_left:
    
    # 🌟 第一板块：顶部模式切换
    with st.container(border=True):

        st.markdown("<h4 style='color: #1e293b; font-weight: 700; margin-bottom: 20px;'>业务控制中心</h4>", unsafe_allow_html=True)
        
        new_mode = st.radio("系统运行模式", ["1. 订单规划", "2. 路线导航"], label_visibility="collapsed")
        if new_mode != st.session_state.business_mode:
            st.session_state.business_mode = new_mode
            st.session_state.messages = [] 
            st.session_state.ui_state = "normal"
            st.session_state.blocked_road = None 
            st.rerun()

    # 🌟 第二板块：底部订单与指标
    with st.container(border=True):
        # 👇 核心修改：把它挪到 if 的上方！作为进入盒子的第一步，确保任何模式下它都存在
        route_details_placeholder = st.empty() 
        
        if st.session_state.business_mode == "1. 订单规划":
            st.markdown("<div style='font-size: 1.15em; font-weight: 800; color: #1e293b; margin-bottom: 12px; border-left: 4px solid #3b82f6; padding-left: 8px;'>选择调度订单</div>", unsafe_allow_html=True)
            
            selected_order = st.selectbox("请选择待调度订单编号", [
                "ORD-901 (西财光华校区南门)", 
                "ORD-902 (金沙遗址/城西)", 
                "ORD-903 (成都东站/城东)"
            ], label_visibility="collapsed")

            if selected_order != st.session_state.prev_order:
                st.session_state.prev_order = selected_order
                st.session_state.ui_state = "normal"
                st.session_state.blocked_road = None
                st.rerun()  # 触发重绘
            
            st.markdown("<hr style='border: 1px solid rgba(255, 255, 255, 0.5); margin: 20px 0;'>", unsafe_allow_html=True)
            st.markdown("<div style='font-size: 1.15em; font-weight: 800; color: #1e293b; margin-bottom: 15px; border-left: 4px solid #3b82f6; padding-left: 8px;'>运行状态指标</div>", unsafe_allow_html=True)
            
            status = "✅ 路线已重构 (出车就绪)" if st.session_state.ui_state == "rerouted" else "待出车 (目前路线通畅)"
            render_kpi_card("当前选中单状态", status)
            
            if st.session_state.ui_state == "rerouted" and "901" in selected_order:
                render_kpi_card("路网干扰事件", f"道路发生事故或零时管制：{st.session_state.blocked_road or '天府三街'}", is_alert=True)
                
            # 🚨 记得把之前呆在这里的 route_details_placeholder = st.empty() 这一行删掉
                
        else:
            st.markdown("<div style='font-size: 1.15em; font-weight: 800; color: #1e293b; margin-bottom: 15px; border-left: 4px solid #3b82f6; padding-left: 8px;'>导航状态指标</div>", unsafe_allow_html=True)
            render_kpi_card("任务类型", "点对点直达导航")
            render_kpi_card("起始区域", st.session_state.start_point)
            render_kpi_card("终到区域", st.session_state.end_point)

# ==================== 中间：AI 指令终端 ====================
with col_mid:
    st.markdown("<h4 style='color: #1e293b; font-weight: 800; margin-bottom: 2px;'>智能决策终端</h4>", unsafe_allow_html=True)
    st.markdown("<p style='font-size: 1em; color: #10b981; margin-top: 0px; margin-bottom: 15px; font-weight: 600; letter-spacing: 0.5px;'>Powered by DeepSeek V3</p>", unsafe_allow_html=True)
    
    chat_container = st.container(height=920, border=False)
    
    with chat_container:
        if not st.session_state.messages:
            welcome_msg = "您好！全局调度终端已就绪。请选择左侧订单编号并输入指令，例如：'天府大道发生拥堵，马上改道'。" if st.session_state.business_mode == "1. 订单规划" else "您好！动态导航已就绪。由于需要实时调用高德API，解析可能需要3~4秒，请稍候。例如：'从西南财经大学光华校区南门导航去成都太古里'。"
            st.session_state.messages.append({"role": "assistant", "content": welcome_msg})

        for msg in st.session_state.messages:
            background_color = "#e0e7ff" if msg["role"] == "assistant" else "#ffffff"
            st.markdown(f"""
            <div style="background-color: {background_color}; border-radius: 6px; padding: 12px; border: 1px solid #e2e8f0; margin-bottom: 8px; font-size: 0.95em; line-height: 1.5;">
                {msg['content']}
            </div>
            """, unsafe_allow_html=True)
            
    if prompt := st.chat_input("输入路况反馈或调度指令..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        
        with st.spinner("DeepSeek 大模型正在解析语义与约束..."):
            parsed_params = parse_dispatch_intent(prompt, DEEPSEEK_API_KEY)
            
        if parsed_params:
            if parsed_params.get("blocked_road"):
                st.session_state.ui_state = "rerouted"
                st.session_state.blocked_road = parsed_params["blocked_road"]
                reply = f"已经更新道路信息，系统已识别受控路段 `[{st.session_state.blocked_road}]`，重排线已完成。"
            elif parsed_params.get("start_point") and parsed_params.get("end_point"):
                st.session_state.start_point = parsed_params["start_point"]
                st.session_state.end_point = parsed_params["end_point"]
                reply = f"路由参数匹配成功。引擎正在检索坐标并进行Dijkstra最短路径重算。请查看右侧地图。"
            else:
                reply = "指令解析完毕，未检测到动态约束变更。寻路引擎正维持标准基线运行。"
        else:
            reply = "服务响应异常，请检查API状态。"
                
        st.session_state.messages.append({"role": "assistant", "content": reply})
        st.rerun()

# ==================== 右侧：常驻大地图 ====================
with col_right:
    current_constraints = {}
    if st.session_state.business_mode == "1. 订单规划":
        current_constraints["order_id"] = selected_order
    else:
        current_constraints["start_point"] = st.session_state.start_point
        current_constraints["end_point"] = st.session_state.end_point
        
    if st.session_state.ui_state == "rerouted":
        current_constraints["blocked_road"] = st.session_state.blocked_road

    route_result = calculate_routes(current_constraints, G, nodes_gdf, st.session_state.business_mode)

    if route_result:

        streets = []
        if st.session_state.ui_state == "rerouted" and route_result.get("new_street_names"):
            streets = route_result["new_street_names"][0]
        elif route_result.get("original_street_names"):
            streets = route_result["original_street_names"][0]
            
        if streets:
            # 🌟 核心升级：将路名构建为高级 SaaS 风格的流式 Tag 标签
            tags_html = ""
            for i, street in enumerate(streets):
                # 智能识别当前路段是否为“拥堵熔断路段”，自动触发警示红高亮
                is_blocked = (st.session_state.ui_state == "rerouted" and 
                              st.session_state.blocked_road and 
                              st.session_state.blocked_road in street)
                
                # 定义标签的独立样式
                tag_bg = "rgba(254, 226, 226, 0.8)" if is_blocked else "rgba(241, 245, 249, 0.7)"
                tag_border = "rgba(239, 68, 68, 0.4)" if is_blocked else "rgba(226, 232, 240, 0.9)"
                tag_text = "#ef4444" if is_blocked else "#334155"
                font_weight = "800" if is_blocked else "600"
                
                # 单个路名标签的 HTML
                tags_html += f'<span style="background: {tag_bg}; border: 1px solid {tag_border}; color: {tag_text}; padding: 4px 10px; border-radius: 6px; font-size: 0.85em; font-weight: {font_weight}; display: inline-block; margin-bottom: 8px; box-shadow: 0 1px 2px rgba(0,0,0,0.02);">{street}</span>'
                
                # 两个标签之间的连接箭头
                if i < len(streets) - 1:
                    tags_html += '<span style="color: #cbd5e1; font-size: 0.8em; margin: 0 6px; display: inline-block; transform: translateY(-1px);">➔</span>'

            # 整体面板完美对齐上面 KPI 卡片的 UI 风格
            route_details_placeholder.markdown(f"""
            <div style="background: rgba(255, 255, 255, 0.5); backdrop-filter: blur(10px); -webkit-backdrop-filter: blur(10px); padding: 15px 15px 5px 15px; border-radius: 12px; border: 1px solid rgba(255, 255, 255, 0.8); margin-bottom: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.02);">
                <div style="font-size: 1.05em; color: #475569; font-weight: 500; margin-bottom: 16px;">实时轨迹解析</div>
                <div style="line-height: 1.8;">
                    {tags_html}
                </div>
            </div>
            """, unsafe_allow_html=True)

        if not route_result["depot"]["coords"]:
            st.error("无法找到匹配的地名，请检查输入或高德API Key有效性。")
        else:
            lats = [route_result["depot"]["coords"][1]]
            lons = [route_result["depot"]["coords"][0]]
            
            nodes_list = [{"name": route_result["depot"]["node_name"], "lat": lats[0], "lon": lons[0], "color": [26, 115, 232]}]
            
            for c in route_result["customers"]:
                if c.get("coords"): 
                    nodes_list.append({"name": c['name'], "lat": c['coords'][1], "lon": c['coords'][0], "color": [234, 67, 53]})
                    lats.append(c['coords'][1])
                    lons.append(c['coords'][0])
            nodes_df = pd.DataFrame(nodes_list)
            
            center_lat = sum(lats) / len(lats)
            center_lon = sum(lons) / len(lons)
            zoom_level = 11.2 if len(lats) > 1 else 13.0
            
            layers = []
            if st.session_state.ui_state == "normal":
                if route_result["original_routes"] and route_result["original_routes"][0]:
                    layers.append(pdk.Layer("PathLayer", data=pd.DataFrame([{"path": route_result["original_routes"][0]}]), get_path="path", get_color=[26, 115, 232, 200], get_width=25, width_min_pixels=1, width_max_pixels=6))
            else:
                if route_result["original_routes"] and route_result["original_routes"][0]:
                    layers.append(pdk.Layer(
                        "PathLayer", 
                        data=pd.DataFrame([{"path": route_result["original_routes"][0]}]), 
                        get_path="path", 
                        get_color=[239, 68, 68, 150],  # 🔴 半透明警戒红 (透明度降至120)
                        get_width=20,                  # 宽度调细，形成废弃感
                        width_min_pixels=1.5, 
                        width_max_pixels=4  
                    ))
                # 算出的新路线变成亮绿色粗实线，叠加在上方
                if route_result.get("new_routes") and route_result["new_routes"][0]:
                    layers.append(pdk.Layer("PathLayer", data=pd.DataFrame([{"path": route_result["new_routes"][0]}]), get_path="path", get_color=[46, 204, 113, 255], get_width=25, width_min_pixels=1.5, width_max_pixels=4))

            layers.append(pdk.Layer("ScatterplotLayer", data=nodes_df, get_position='[lon, lat]', get_fill_color='color', get_radius=250, radius_min_pixels=4, radius_max_pixels=15, pickable=True))
            
            st.pydeck_chart(pdk.Deck(
                layers=layers, 
                initial_view_state=pdk.ViewState(latitude=center_lat, longitude=center_lon, zoom=zoom_level, pitch=0, bearing=0),
                map_style='https://basemaps.cartocdn.com/gl/positron-gl-style/style.json',
                tooltip={"text": "{name}"}
            ))