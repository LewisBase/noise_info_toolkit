"""
简单的WebSocket测试客户端，用于诊断连接问题
"""
import websocket
import ssl
import time

def on_message(ws, message):
    print(f"收到消息: {message}")

def on_error(ws, error):
    print(f"错误: {error}")

def on_close(ws, close_status_code, close_msg):
    print("WebSocket连接已关闭")

def on_open(ws):
    print("WebSocket连接已建立")
    # 发送测试消息
    ws.send("Hello WebSocket!")

if __name__ == "__main__":
    # 启用调试模式
    websocket.enableTrace(True)
    
    # WebSocket服务器地址
    websocket_url = "ws://localhost:8000/ws"
    
    print(f"正在连接到: {websocket_url}")
    
    # 创建WebSocket应用
    ws = websocket.WebSocketApp(websocket_url,
                                on_open=on_open,
                                on_message=on_message,
                                on_error=on_error,
                                on_close=on_close)
    
    # 连接并运行
    ws.run_forever()