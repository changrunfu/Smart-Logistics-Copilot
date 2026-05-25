from openai import OpenAI
import httpx
import json

def parse_dispatch_intent(user_input, api_key):
    client = OpenAI(
        api_key=api_key, 
        base_url="https://api.deepseek.com/v1",  
        http_client=httpx.Client(proxy=None, trust_env=False, timeout=30.0) 
    )
    
    system_prompt = """
    你是一个物流系统的指令提取器。
    请提取以下字段（未提及则为 null），以 JSON 输出：
    - "start_point": 起点名称
    - "end_point": 终点名称
    - "blocked_road": 需要避开/封路的街道名称
    
    示例：{"start_point": "中心仓", "end_point": "天府软件园", "blocked_road": "天府三街"}
    """
    
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_input}
            ],
            response_format={"type": "json_object"},
            temperature=0.0,
            max_tokens=100
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        return {"error": str(e), "start_point": None, "end_point": None, "blocked_road": None}