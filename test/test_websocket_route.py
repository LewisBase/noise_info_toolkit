"""
测试WebSocket路由是否正确注册
"""
from main import app
import uvicorn

def test_websocket_routes():
    # 获取所有路由
    routes = app.routes
    
    print("所有注册的路由:")
    websocket_routes = []
    http_routes = []
    
    for route in routes:
        if hasattr(route, 'endpoint'):
            if 'websocket' in str(type(route)).lower():
                websocket_routes.append(route)
                print(f"WebSocket路由: {route.path}")
            else:
                http_routes.append(route)
                print(f"HTTP路由: {route.path} -> {route.endpoint.__name__}")
    
    print(f"\n总共找到 {len(http_routes)} 个HTTP路由和 {len(websocket_routes)} 个WebSocket路由")
    
    # 检查/ws路由是否存在
    ws_route_exists = any(route.path == '/ws' for route in websocket_routes)
    if ws_route_exists:
        print("\n✓ WebSocket路由 '/ws' 已正确注册")
    else:
        print("\n✗ WebSocket路由 '/ws' 未找到")
        
    return ws_route_exists

if __name__ == "__main__":
    test_websocket_routes()