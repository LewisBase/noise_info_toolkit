"""
WebSocket client for testing real-time audio processing updates
"""
import asyncio
import websockets
import json

async def test_websocket_client():
    """Test WebSocket client to receive real-time updates"""
    uri = "ws://localhost:8000/ws"
    
    try:
        async with websockets.connect(uri) as websocket:
            print(f"Connected to WebSocket server at {uri}")
            print("Waiting for real-time audio processing updates...")
            print("Send 'quit' to exit the client")
            
            # Create a task to listen for messages
            async def listen():
                while True:
                    try:
                        message = await websocket.recv()
                        try:
                            # Try to parse as JSON
                            data = json.loads(message)
                            print(f"Received audio processing results:")
                            print(json.dumps(data, indent=2, ensure_ascii=False))
                        except json.JSONDecodeError:
                            # Plain text message
                            print(f"Received: {message}")
                    except websockets.exceptions.ConnectionClosed:
                        print("Connection closed by server")
                        break
                    except Exception as e:
                        print(f"Error receiving message: {e}")
                        break
            
            # Create a task to send messages
            async def send():
                loop = asyncio.get_event_loop()
                while True:
                    try:
                        # Get input from user
                        message = await loop.run_in_executor(None, input, "Enter message (or 'quit' to exit): ")
                        if message.lower() == 'quit':
                            break
                        await websocket.send(message)
                    except Exception as e:
                        print(f"Error sending message: {e}")
                        break
            
            # Run both tasks concurrently
            await asyncio.gather(listen(), send())
            
    except Exception as e:
        print(f"Failed to connect to WebSocket server: {e}")

if __name__ == "__main__":
    asyncio.run(test_websocket_client())