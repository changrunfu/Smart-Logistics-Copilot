import osmnx as ox
import networkx as nx
import streamlit as st
import requests
import math
import os
from dotenv import load_dotenv

# 自动寻找并读取 .env 文件里的变量
load_dotenv() 

# 读取你的密钥 (注意：括号里的名字必须和你在 .env 里写的一模一样)
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
GAODE_API_KEY = os.getenv("GAODE_API_KEY")


# --- 1. 高精度坐标系转换算法 (GCJ-02 -> WGS-84) ---
PI = 3.1415926535897932384626
A = 6378245.0  
EE = 0.00669342162296594323  

def _transform_lat(lng, lat):
    ret = -100.0 + 2.0 * lng + 3.0 * lat + 0.2 * lat * lat + 0.1 * lng * lat + 0.2 * math.sqrt(math.fabs(lng))
    ret += (20.0 * math.sin(6.0 * lng * PI) + 20.0 * math.sin(2.0 * lng * PI)) * 2.0 / 3.0
    ret += (20.0 * math.sin(lat * PI) + 40.0 * math.sin(lat / 3.0 * PI)) * 2.0 / 3.0
    ret += (160.0 * math.sin(lat / 12.0 * PI) + 320 * math.sin(lat * PI / 30.0)) * 2.0 / 3.0
    return ret

def _transform_lng(lng, lat):
    ret = 300.0 + lng + 2.0 * lat + 0.1 * lng * lng + 0.1 * lng * lat + 0.1 * math.sqrt(math.fabs(lng))
    ret += (20.0 * math.sin(6.0 * lng * PI) + 20.0 * math.sin(2.0 * lng * PI)) * 2.0 / 3.0
    ret += (20.0 * math.sin(lng * PI) + 40.0 * math.sin(lng / 3.0 * PI)) * 2.0 / 3.0
    ret += (150.0 * math.sin(lng / 12.0 * PI) + 300.0 * math.sin(lng / 30.0 * PI)) * 2.0 / 3.0
    return ret

def gcj02_to_wgs84(lng, lat):
    if not (lng > 73.66 and lng < 135.05 and lat > 3.86 and lat < 53.55): return lng, lat
    dlat = _transform_lat(lng - 105.0, lat - 35.0)
    dlng = _transform_lng(lng - 105.0, lat - 35.0)
    radlat = lat / 180.0 * PI
    magic = math.sin(radlat)
    magic = 1 - EE * magic * magic
    sqrtmagic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((A * (1 - EE)) / (magic * sqrtmagic) * PI)
    dlng = (dlng * 180.0) / (A / sqrtmagic * math.cos(radlat) * PI)
    mglat = lat + dlat
    mglng = lng + dlng
    wgs_lng = lng * 2 - mglng
    wgs_lat = lat * 2 - mglat
    return wgs_lng, wgs_lat

def get_location_from_gaode(address):
    url = f"https://restapi.amap.com/v3/geocode/geo?address={address}&city=成都市&key={GAODE_API_KEY}"
    try:
        response = requests.get(url).json()
        if response.get('status') == '1' and int(response.get('count', 0)) > 0:
            location = response['geocodes'][0]['location']
            gcj_lon, gcj_lat = map(float, location.split(','))
            wgs_lon, wgs_lat = gcj02_to_wgs84(gcj_lon, gcj_lat)
            return wgs_lon, wgs_lat
    except Exception as e: 
        print(f"高德 API 请求失败: {e}")
    return None, None


# --- 2. 混合架构：热数据极速缓存 ---
ADDRESS_BOOK = {
    "总调配中心": (104.0728, 30.6968),      
    "春熙路 IFS": (104.0818, 30.6559),      
    "天府软件园": (104.0678, 30.5469),    
    "西财光华校区南门": (104.0143, 30.6605),  
    "金沙遗址": (104.0116, 30.6738),        
    "成都东站": (104.1416, 30.6288),        
    "天府三街": (104.0768, 30.5828)         
}

@st.cache_resource
def load_local_network():
    # 🚨 替换为你真实的本地 GraphML 路径
    graph_path = r"C:\Users\20331\Desktop\Thesis\code\chengdu_radius_drive_network.graphml"
    G = ox.load_graphml(graph_path)
    nodes_gdf, edges_gdf = ox.graph_to_gdfs(G, nodes=True, edges=True)
    return G, nodes_gdf

def get_nearest_node(G, nodes_gdf, address_name, mode):
    """根据业务模式智能分流：订单模式走本地字典，导航模式走高德 API"""
    if not address_name: return None, None
    clean_input = str(address_name).strip().lower()
        
    for key, coords in ADDRESS_BOOK.items():
        clean_key = str(key).strip().lower()
        if clean_input in clean_key or clean_key in clean_input:
            lon, lat = coords
            node_id = ox.distance.nearest_nodes(G, X=lon, Y=lat)
            true_lon = float(nodes_gdf.loc[node_id]['x'])
            true_lat = float(nodes_gdf.loc[node_id]['y'])
            return node_id, [true_lon, true_lat]
            
    if mode == "1. 订单规划":
        return None, None
        
    api_query = clean_input
    if clean_input.isalpha() and len(clean_input) < 6: 
        api_query = f"成都{clean_input}"
        
    lon, lat = get_location_from_gaode(api_query)
    if lon and lat:
        node_id = ox.distance.nearest_nodes(G, X=lon, Y=lat)
        true_lon = float(nodes_gdf.loc[node_id]['x'])
        true_lat = float(nodes_gdf.loc[node_id]['y'])
        return node_id, [true_lon, true_lat]
        
    return None, None

def get_true_geometry_path(G, path_nodes, nodes_gdf):
    if not path_nodes: return []
    coords = []
    for i in range(len(path_nodes) - 1):
        u, v = path_nodes[i], path_nodes[i+1]
        edge_data = min(G[u][v].values(), key=lambda d: d.get("length", float('inf')))
        if 'geometry' in edge_data:
            xs, ys = edge_data['geometry'].xy
            for x, y in zip(xs[:-1], ys[:-1]): coords.append([x, y])
        else:
            coords.append([float(nodes_gdf.loc[u]['x']), float(nodes_gdf.loc[u]['y'])])
    coords.append([float(nodes_gdf.loc[path_nodes[-1]]['x']), float(nodes_gdf.loc[path_nodes[-1]]['y'])])
    return coords

def get_path_street_names(G, path_nodes):
    """提取拓扑路径上的真实物理道路名称，并进行连续去重处理"""
    if not path_nodes: return []
    streets = []
    for i in range(len(path_nodes) - 1):
        u, v = path_nodes[i], path_nodes[i+1]
        # 获取两点之间最短的那条边的属性
        edge_data = min(G[u][v].values(), key=lambda d: d.get("length", float('inf')))
        name = edge_data.get('name')
        if name:
            # 有时一条路有多个名字(列表)，取主要名字
            if isinstance(name, list): name = name[0]
            name = str(name)
            # 防止同名的连续路段重复出现（去重）
            if not streets or streets[-1] != name:
                streets.append(name)
    
    # 如果路网太偏僻没有名字，给一个兜底显示
    if not streets:
        return ["未命名道路 (路网支线)"]
    return streets


# --- 3. 核心寻路与熔断计算逻辑 ---
def calculate_routes(constraints, G, nodes_gdf, mode):
    start_node, start_coords = None, None
    end_nodes, customers_info = [], []

    if mode == "1. 订单规划":
        start_node, start_coords = get_nearest_node(G, nodes_gdf, "总调配中心", mode)
        order_id = constraints.get("order_id", "")
        if "ORD-901" in order_id:
            node, coords = get_nearest_node(G, nodes_gdf, "西财光华校区南门", mode)
            customers_info.append({"coords": coords, "name": "ORD-901 (西财光华校区南门)"})
        elif "ORD-902" in order_id:
            node, coords = get_nearest_node(G, nodes_gdf, "金沙遗址", mode)
            customers_info.append({"coords": coords, "name": "ORD-902 (城西方向)"})
        else:
            node, coords = get_nearest_node(G, nodes_gdf, "成都东站", mode)
            customers_info.append({"coords": coords, "name": "ORD-903 (城东方向)"})
        end_nodes.append(node)
    else:
        sp_name = constraints.get("start_point") or "春熙路 IFS"
        ep_name = constraints.get("end_point") or "西财光华校区南门"
        start_node, start_coords = get_nearest_node(G, nodes_gdf, sp_name, mode)
        node, coords = get_nearest_node(G, nodes_gdf, ep_name, mode)
        end_nodes.append(node)
        customers_info.append({"coords": coords, "name": ep_name})

    orig_path_coords = []
    orig_street_names = [] # 🌟 新增：存放原始路名
    for end_node in end_nodes:
        if start_node is None or end_node is None:
            orig_path_coords.append([])
            orig_street_names.append([])
            continue
        try:
            path_nodes = nx.shortest_path(G, start_node, end_node, weight='length')
            orig_path_coords.append(get_true_geometry_path(G, path_nodes, nodes_gdf))
            orig_street_names.append(get_path_street_names(G, path_nodes)) # 🌟 提取路名
        except nx.NetworkXNoPath:
            try:
                G_un = G.to_undirected()
                path_nodes = nx.shortest_path(G_un, start_node, end_node, weight='length')
                orig_path_coords.append(get_true_geometry_path(G_un, path_nodes, nodes_gdf))
                orig_street_names.append(get_path_street_names(G_un, path_nodes)) # 🌟 提取路名
            except Exception:
                orig_path_coords.append([start_coords, customers_info[0]["coords"]])
                orig_street_names.append(["直线飞线兜底路段"])

    new_path_coords = []
    new_street_names = [] # 🌟 新增：存放改道后的新路名
    blocked_road = constraints.get("blocked_road")
    
    if blocked_road:
        G_temp = G.copy()
        edges_to_remove = [(u, v, key) for u, v, key, data in G_temp.edges(keys=True, data=True) if blocked_road in str(data.get('name', ''))]
        G_temp.remove_edges_from(edges_to_remove)

        for end_node in end_nodes:
            if start_node is None or end_node is None:
                new_path_coords.append([])
                new_street_names.append([])
                continue
            try:
                path_nodes = nx.shortest_path(G_temp, start_node, end_node, weight='length')
                new_path_coords.append(get_true_geometry_path(G_temp, path_nodes, nodes_gdf))
                new_street_names.append(get_path_street_names(G_temp, path_nodes)) # 🌟 提取路名
            except nx.NetworkXNoPath:
                try:
                    G_temp_un = G_temp.to_undirected()
                    path_nodes = nx.shortest_path(G_temp_un, start_node, end_node, weight='length')
                    new_path_coords.append(get_true_geometry_path(G_temp_un, path_nodes, nodes_gdf))
                    new_street_names.append(get_path_street_names(G_temp_un, path_nodes)) # 🌟 提取路名
                except:
                    new_path_coords.append([start_coords, customers_info[0]["coords"]])
                    new_street_names.append(["无备用路线，飞线兜底"])

    return {
        "depot": {"coords": start_coords, "node_name": "📍 起点" if mode == "2. 路线导航" else "🏢 总调配中心"},
        "customers": customers_info,
        "original_routes": orig_path_coords,
        "original_street_names": orig_street_names, # 🌟 传出数据
        "new_routes": new_path_coords if blocked_road else None,
        "new_street_names": new_street_names if blocked_road else None # 🌟 传出数据
    }