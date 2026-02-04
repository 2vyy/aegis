"""
NiceGUI Web Frontend for Sentinel.
Implements the "Defense-Grade" Dark Mode UI.
"""
from nicegui import ui
import logging
import cv2
import base64
import numpy as np
from server_node.webrtc.receiver import latest_frames

logger = logging.getLogger("web_ui")

@ui.page('/')
def index_page():
    """Initialize the NiceGUI layout."""
    
    # THEME: Dark Mode & Slate Background
    # Slate 900: #0f172a, Slate 700: #334155 (grid lines)
    ui.colors(primary='#3b82f6', accent='#ef4444', dark='#0f172a')
    
    # Global CSS for "Defense" look
    ui.query('body').style('background-color: #0f172a; color: #e2e8f0;')
    ui.add_head_html('''
        <style>
            .defense-border { border: 1px solid #334155; }
            .defense-card { background-color: #1e293b; border: 1px solid #334155; }
            .defense-text { font-family: 'Roboto Mono', monospace; }
        </style>
    ''')
    
    # --- DRAWER: Asset Status ---
    with ui.right_drawer(value=False).classes('bg-gray-900 border-l defense-border p-4') as status_drawer:
        ui.label('ASSET STATUS').classes('text-lg font-mono text-blue-400 mb-4 tracking-widest')
        
        # Dynamic Table
        columns = [
            {'name': 'id', 'label': 'ID', 'field': 'id', 'align': 'left'},
            {'name': 'status', 'label': 'STAT', 'field': 'status', 'align': 'left'},
            {'name': 'bw', 'label': 'BW', 'field': 'bw', 'align': 'right'},
        ]
        status_table = ui.table(columns=columns, rows=[], pagination=None).classes('w-full defense-text text-xs')
        
        def update_assets():
            # logger.info("Updating asset status...")
            from server_node.webrtc.receiver import connected_cameras
            from server_node.core.asset_manager import asset_manager
            
            # Sync runtime status to Asset Manager
            # Map Camera 0 -> CAM_01_NORTH_GATE for demo
            is_connected = 0 in connected_cameras or '0' in connected_cameras
            asset_manager.update_status(0, is_connected)
            
            rows = []
            for asset in asset_manager.assets.values():
                 status_icon = '🟢' if asset.status == 'ONLINE' else '🔴'
                 bw_val = '2.4M' if asset.status == 'ONLINE' else '0'
                 rows.append({'id': asset.id, 'status': f'{status_icon} {asset.status}', 'bw': bw_val})
                 
            status_table.rows = rows
            status_table.update()
        
        # Update when drawer is toggled
        ui.timer(2.0, update_assets) # Auto-refresh every 2s

    with ui.row().classes('w-full h-screen no-wrap p-0 gap-0'):

        # --- PANEL A: Geospatial Map (Left - 60%) ---
        with ui.column().classes('w-3/5 h-full p-2'):
            ui.label('GEOSPATIAL INTEL').classes('text-xs font-mono text-gray-500 tracking-widest mb-1')
            
            from server_node.core.asset_manager import asset_manager
            hq_loc = asset_manager.center_coordinates
            
            # Map Card with Brightness Boost
            with ui.card().classes('w-full h-full bg-gray-900 defense-border p-0 relative').style('filter: brightness(1.2)'):
                m = ui.leaflet(center=hq_loc, zoom=16).classes('w-full h-full')
                
                # Dark Mode Tiles
                m.tile_layer(
                    url_template=r'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
                    options={'attribution': '&copy; OpenStreetMap &copy; CARTO', 'subdomains': 'abcd', 'maxZoom': 20}
                )

                # DYNAMIC SYMBOLOGY (Static Render)
                # Map is drawn once at startup. Cones are constant blue.
                for asset in asset_manager.assets.values():
                    # 1. Camera Icon (Triangle)
                    cam_lat, cam_lon = asset.lat, asset.lon
                    
                    m.generic_layer(
                        name='polygon',
                        args=[[
                            (cam_lat + 0.0001, cam_lon),
                            (cam_lat - 0.0001, cam_lon - 0.0001),
                            (cam_lat - 0.0001, cam_lon + 0.0001)
                        ], {'color': '#4ade80', 'fillColor': '#4ade80', 'fillOpacity': 1.0, 'weight': 0}]
                    )
                    
                    # 2. FOV Cone
                    import math
                    length = 0.0015 
                    angle_left = math.radians(asset.heading - asset.fov/2)
                    angle_right = math.radians(asset.heading + asset.fov/2)
                    
                    p1 = (cam_lat + length * math.cos(angle_left),  cam_lon + length * math.sin(angle_left))
                    p2 = (cam_lat + length * math.cos(angle_right), cam_lon + length * math.sin(angle_right))
                    
                    # Color Logic: Constant Blue (Covered Area)
                    cone_color = '#3b82f6'
                    cone_opacity = 0.15
                    
                    m.generic_layer(
                        name='polygon',
                        args=[[
                            (cam_lat, cam_lon),  # Origin
                            p1,
                            p2
                        ], {
                            'color': cone_color, 
                            'fillColor': cone_color, 
                            'fillOpacity': cone_opacity, 
                            'weight': 1, 
                            'dashArray': '5, 5'
                        }]
                    )

        # --- RIGHT COLUMN (Video + Logs) ---
        with ui.column().classes('w-2/5 h-full p-2 gap-2'):
            
            # --- PANEL B: Sensor Array ---
            ui.label('PRIMARY SENSOR FEED').classes('text-xs font-mono text-gray-500 tracking-widest')
            with ui.card().classes('w-full h-1/2 bg-black border-l-4 border-red-500 relative p-0 items-center justify-center'):
                video_image = ui.interactive_image().classes('w-full h-full object-contain').style('display: none;')
                no_signal = ui.column().classes('absolute-center items-center')
                with no_signal:
                    ui.spinner('dots', size='lg', color='red')
                    ui.label('NO UPLINK').classes('text-red-500 font-mono text-xs mt-2')

                ui.label('LIVE').classes('absolute top-2 left-2 text-green-500 text-xs font-mono z-10')
                ui.label('CAM_04').classes('absolute top-2 right-2 text-white text-xs font-mono z-10')

                async def update_video_feed():
                    frame = latest_frames.get(0)
                    if frame is not None:
                        _, buffer = cv2.imencode('.jpg', frame)
                        jpg_as_text = base64.b64encode(buffer).decode('utf-8')
                        video_image.set_source(f'data:image/jpeg;base64,{jpg_as_text}')
                        video_image.style('display: block;')
                        no_signal.set_visibility(False)
                    else:
                        video_image.style('display: none;')
                        no_signal.set_visibility(True)
                ui.timer(0.05, update_video_feed)
                
            # --- PANEL C: Intel Feed ---
            ui.row().classes('w-full justify-between items-center')
            ui.label('TACTICAL LOGS').classes('text-xs font-mono text-gray-500 tracking-widest')
            
            # Drawer Toggle Button
            ui.button('STATUS PANEL', on_click=status_drawer.toggle).classes('text-xs bg-gray-800 text-blue-300 border defense-border px-2')
            
            log_container = ui.scroll_area().classes('w-full h-1/2 bg-gray-950 defense-border p-2 font-mono text-xs')
            
            with log_container:
                log_list = ui.column().classes('w-full gap-1')
            
            from server_node.logging import log_buffer
            
            async def update_logs():
                log_list.clear()
                with log_list:
                    # Show last 20 logs to avoid DOM overload
                    for log_entry in list(log_buffer)[-20:]:
                        # Simple keyword highlighting
                        color_class = 'text-gray-400'
                        if 'DETECTION' in log_entry or 'motion' in log_entry.lower():
                            color_class = 'text-red-400 font-bold'
                        elif 'SYS' in log_entry:
                            color_class = 'text-blue-400'
                        elif 'NET' in log_entry:
                            color_class = 'text-yellow-500'
                        elif 'AI' in log_entry:
                            color_class = 'text-green-400'
                        
                        ui.label(log_entry).classes(color_class)
                
            # Update logs every 200ms
            ui.timer(0.2, update_logs)

    logger.info("UI initialized")
