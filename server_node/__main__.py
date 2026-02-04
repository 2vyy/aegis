"""Main entry point for server_node.

Integrates NiceGUI frontend with WebRTC signaling backend.
"""
import uvicorn
from nicegui import ui
from server_node.logging import setup_logging
from server_node.webrtc.receiver import app as signaling_app
import server_node.web.app # Register routes

def main():
    """Start the server node."""
    setup_logging(level="INFO")
    
    # Initialize the NiceGUI UI (Sidebar effect of import)
    # from server_node.web.app import index_page  <-- already imported
    pass
    
    # Attach NiceGUI to the existing FastAPI signaling app
    # This mounts NiceGUI at root (/) and allows our /offer endpoint to coexist
    ui.run_with(
        signaling_app, 
        title='Sentinel Dashboard',
        dark=True,
    )
    
    print("Starting Sentinel Server Node...")
    print("WebRTC signaling & Web UI on http://0.0.0.0:8000")
    
    # Run the combined app
    uvicorn.run(signaling_app, host="0.0.0.0", port=8000, log_level="warning")

if __name__ == "__main__":
    main()
