"""
NiceGUI Web Frontend for Sentinel.
Implements the "Defense-Grade" Dark Mode UI.
"""
from nicegui import ui
import logging
import cv2
import base64
import numpy as np
import os
from server_node.webrtc.receiver import latest_frames

logger = logging.getLogger("web_ui")

@ui.page('/')
def index_page():
    # Register Clean Shutdown
    from nicegui import app
    from server_node.webrtc.receiver import cleanup
    app.on_shutdown(cleanup)

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
            .q-loading-bar { display: none !important; } /* Hide loading indicator */
        </style>
        <script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
        <script>
            var hls = null;
            function loadHLS() {
                var video = document.getElementById('hls-video');
                if (!video) return; 
                
                // Add timestamp to prevent browser caching of the manifest
                var videoSrc = '/recordings/0/stream.m3u8?t=' + new Date().getTime();
                
                // Cleanup existing instance
                if (hls) {
                    hls.destroy();
                    hls = null;
                }

                if (Hls.isSupported()) {
                    hls = new Hls({
                        debug: false, 
                        manifestLoadingTimeOut: 10000,
                        manifestLoadingMaxRetry: 10,
                        levelLoadingTimeOut: 10000,
                        // fMP4 specific optimizations
                        enableWorker: true,
                        lowLatencyMode: true,
                    });
                    
                    hls.loadSource(videoSrc);
                    hls.attachMedia(video);
                    
                    hls.on(Hls.Events.MANIFEST_PARSED, function() {
                        console.log("Sentinel Player: Manifest Parsed");
                        video.muted = true; // Auto-play often requires mute first
                        video.play().catch(e => console.error("Auto-play failed:", e));
                    });
                    
                    hls.on(Hls.Events.ERROR, function(event, data) {
                        console.error("HLS Error:", data);
                        if (data.fatal) {
                            switch(data.type) {
                                case Hls.ErrorTypes.NETWORK_ERROR:
                                    console.log("Network error, trying to recover...");
                                    hls.startLoad();
                                    break;
                                case Hls.ErrorTypes.MEDIA_ERROR:
                                    console.log("Media error, trying to recover...");
                                    hls.recoverMediaError();
                                    break;
                                default:
                                    hls.destroy();
                                    break;
                            }
                        }
                    });
                }
                else if (video.canPlayType('application/vnd.apple.mpegurl')) {
                    video.src = videoSrc;
                    video.addEventListener('loadedmetadata', function() {
                        video.play();
                    });
                }
            }
        </script>
    ''')
    
    # --- STATIC FILES: Recordings & Snapshots & Assets ---
    recordings_path = os.path.join(os.getcwd(), 'recordings')
    app.add_static_files('/recordings', recordings_path)
    
    snapshots_path = os.path.join(os.getcwd(), 'snapshots')
    app.add_static_files('/snapshots', snapshots_path)
    
    assets_path = os.path.join(os.getcwd(), 'assets')
    app.add_static_files('/assets', assets_path)

    # --- LEFT DRAWER: Playback Replay ---
    with ui.left_drawer(value=False).classes('bg-gray-900 border-r defense-border p-4 w-96') as replay_drawer:
        ui.label('24H REPLAY BUFFER').classes('text-lg font-mono text-red-400 mb-4 tracking-widest')
        ui.label('CAM_01_NORTH_GATE').classes('text-xs text-gray-500 mb-2')
        
        # HLS Player (Structure Only)
        video_html = '''
        <video id="hls-video" controls class="w-full h-48 defense-border bg-black"></video>
        '''
        ui.html(video_html, sanitize=False)
        
        # Init JS (Wait a bit for DOM)
        ui.timer(1.0, lambda: ui.run_javascript('loadHLS()'), once=True)
        
        ui.label('TIMELINE').classes('text-xs text-gray-500 mt-4')
        ui.markdown('> **Buffer**: Last 24h (H.264 @ 15fps).')
        
        # Re-trigger script on click
        ui.button('REFRESH PLAYLIST', on_click=lambda: ui.run_javascript('loadHLS()')).classes('w-full mt-4 bg-red-900 text-white')

    
    # --- DRAWER: Asset Status ---
    with ui.right_drawer(value=False).classes('bg-gray-900 border-l defense-border p-4') as status_drawer:
        # ... (keep existing status drawer content) ...
        ui.label('ASSET STATUS').classes('text-lg font-mono text-blue-400 mb-4 tracking-widest')
        
        # Dynamic Table
        columns = [
            {'name': 'id', 'label': 'ID', 'field': 'id', 'align': 'left'},
            {'name': 'status', 'label': 'STAT', 'field': 'status', 'align': 'left'},
            {'name': 'bw', 'label': 'BW', 'field': 'bw', 'align': 'right'},
        ]
        status_table = ui.table(columns=columns, rows=[], pagination=None).classes('w-full defense-text text-xs')
        
        def update_assets():
            from server_node.webrtc.receiver import connected_cameras
            from server_node.core.asset_manager import asset_manager
            
            is_connected = 0 in connected_cameras or '0' in connected_cameras
            asset_manager.update_status(0, is_connected)
            
            rows = []
            for asset in asset_manager.assets.values():
                 status_icon = '🟢' if asset.status == 'ONLINE' else '🔴'
                 bw_val = '2.4M' if asset.status == 'ONLINE' else '0'
                 rows.append({'id': asset.id, 'status': f'{status_icon} {asset.status}', 'bw': bw_val})
                 
            status_table.rows = rows
            status_table.update()
        
        ui.timer(5.0, update_assets)

    with ui.row().classes('w-full h-screen no-wrap p-0 gap-0'):

        # --- PANEL A: Geospatial Map (Left - 60%) ---
        with ui.column().classes('w-3/5 h-full p-2'):
            # Header with Map Selector
            with ui.row().classes('w-full justify-between items-center mb-1'):
                ui.label('GEOSPATIAL INTEL').classes('text-xs font-mono text-gray-500 tracking-widest')
                
                from server_node.core.asset_manager import asset_manager
                map_options = {mid: m.name for mid, m in asset_manager.maps.items()}
                
                # Default to Global
                current_map_id = 'global'
                
                def on_map_change(e):
                    nonlocal current_map_id
                    current_map_id = e.value
                    m_config = asset_manager.maps[e.value]
                    
                    if m_config.type == 'image':
                        # Image Overlay Mode
                        # 1. Clear Tiles
                        ui.run_javascript(f"var map = getElement({m.id}).map; map.eachLayer(l => {{ if(l instanceof L.TileLayer) map.removeLayer(l); }});")
                        # 2. Add Image
                        # Use JS to add L.imageOverlay
                        bounds_js = str(m_config.bounds) # [[lat1,lon1],[lat2,lon2]]
                        url = m_config.image_url
                        ui.run_javascript(f"""
                            var map = getElement({m.id}).map;
                            // Remove existing image overlays if any
                            map.eachLayer(l => {{ if(l instanceof L.ImageOverlay) map.removeLayer(l); }});
                            
                            L.imageOverlay('{url}', {bounds_js}).addTo(map);
                            map.fitBounds({bounds_js});
                        """)
                    else:
                        # Geospatial Mode
                        # 1. Clear Images
                        ui.run_javascript(f"var map = getElement({m.id}).map; map.eachLayer(l => {{ if(l instanceof L.ImageOverlay) map.removeLayer(l); }});")
                        # 2. Add Tile Layer (if not exists)
                        # We just re-add it via Python which sends the JS command
                        m.tile_layer(
                            url_template=r'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
                            options={'attribution': '&copy; OpenStreetMap &copy; CARTO', 'subdomains': 'abcd', 'maxZoom': 20}
                        )
                        # 3. Fly To
                        m.set_center(m_config.center)
                        m.set_zoom(m_config.zoom)

                ui.select(options=map_options, value='global', on_change=on_map_change).classes('w-48 text-xs').props('dense options-dense filled bg-gray-900')


            hq_loc = asset_manager.center_coordinates
            
            # Map Card
            with ui.card().classes('w-full h-full bg-gray-900 defense-border p-0 relative').style('filter: brightness(1.2)'):
                m = ui.leaflet(center=hq_loc, zoom=16).classes('w-full h-full')
                
                # Dark Mode Tiles (Static - added ONCE initially)
                m.tile_layer(
                    url_template=r'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
                    options={'attribution': '&copy; OpenStreetMap &copy; CARTO', 'subdomains': 'abcd', 'maxZoom': 20}
                )

                # DYNAMIC SYMBOLOGY UPDATE LOOP
                # Safe Clear: Use ui.run_javascript to target the map instance directly.
                # In NiceGUI, the DOM element has a property .map that holds the Leaflet instance.
                # We iterate layers and remove those without a _url (vectors).
                def update_map():
                    # Clear existing vectors
                    ui.run_javascript(f'''
                        var map = getElement({m.id}).map;
                        map.eachLayer(function(l) {{
                            // Keep Tiles (url) and ImageOverlays (imageUrl)
                            // Remove vectors (no url, no imageUrl)
                            if (!l._url && !l._imageUrl && l !== map) {{
                                map.removeLayer(l);
                            }}
                        }});
                    ''')
                    
                    for asset in asset_manager.assets.values():
                        # FILTER: Only show assets for current map
                        if asset.map_id != current_map_id:
                            continue

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
                        
                        # Color Logic: Red (Threat) vs Blue (Idle)
                        is_threat = asset.detection_count > 0
                        cone_color = '#ef4444' if is_threat else '#3b82f6'
                        cone_opacity = 0.4 if is_threat else 0.15
                        
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
                                'dashArray': '5, 5',
                                'className': 'animate-pulse' if is_threat else ''
                            }]
                        )

                # Update map every 2.0s
                ui.timer(2.0, update_map)

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
                ui.timer(0.1, update_video_feed)
                
            # --- PANEL C: Intel Feed ---
            # HEADER
            with ui.row().classes('w-full h-12 items-center justify-between px-2 border-b defense-border'):
                ui.label('SENTINEL // C2 DASBOARD').classes('text-blue-500 font-bold tracking-widest')
                
                with ui.row():
                    # HISTORY Button (New)
                    ui.button('HISTORY', on_click=lambda: ui.navigate.to('/history')).props('flat color=green').classes('mr-2')
                    # Toggle Replay Drawer
                    ui.button('REPLAY', on_click=lambda: replay_drawer.toggle()).props('flat color=red').classes('mr-2')
                    # Toggle Status Drawer
                    ui.button('STATUS', on_click=lambda: status_drawer.toggle()).props('flat color=blue')
            
            ui.label('TACTICAL LOGS').classes('text-xs font-mono text-gray-500 tracking-widest')
            
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
                
            # Update logs every 1.0s
            ui.timer(1.0, update_logs)

    logger.info("UI initialized")


@ui.page('/history')
def history_page():
    """History / Investigation Dashboard"""
    # Force dark theme for consistency
    ui.colors(primary='#3b82f6', accent='#ef4444', dark='#0f172a')
    ui.query('body').style('background-color: #0f172a; color: #e2e8f0;')
    ui.add_head_html('''
        <style>
            .defense-border { border: 1px solid #334155; }
            .defense-card { background-color: #1e293b; border: 1px solid #334155; }
            .defense-text { font-family: 'Roboto Mono', monospace; }
        </style>
    ''')

    # Serve snapshots if not already served (NiceGUI handles dupes gracefully usually, but let's be safe)
    # Actually, we should do this globally, but let's assume it's done at module level or here.
    # Note: app.add_static_files should be top-level.
    
    with ui.column().classes('w-full h-screen p-4 gap-4'):
        # HEADER
        with ui.row().classes('w-full items-center justify-between border-b defense-border pb-2'):
            ui.label('SENTINEL // INVESTIGATION LOGS').classes('text-xl font-mono text-blue-500 tracking-widest')
            ui.button('BACK TO LIVE', on_click=lambda: ui.navigate.to('/')).props('flat color=white icon=arrow_back')

        # DATA FETCHING
        from server_node.core.database import db_manager
        events = db_manager.get_recent_events(limit=100)
        
        # UI: Split View (Table Left, Preview Right) or just a Grid?
        # Let's do a Grid of Cards for visual impact.
        
        with ui.grid(columns=4).classes('w-full gap-4'):
            for event in events:
                # Resolve relative path for web
                # snapshot_path stored as absolute path on disk
                # We need to map it to /snapshots/...
                import os
                filename = os.path.basename(event['snapshot_path'])
                web_path = f"/snapshots/{filename}"
                
                with ui.card().classes('defense-card p-0 gap-0 hover:border-blue-500 cursor-pointer'):
                    # Image Header
                    if filename:
                        ui.image(web_path).classes('w-full h-48 object-cover')
                    else:
                        ui.label('NO IMG').classes('w-full h-48 bg-gray-900 text-center content-center')
                    
                    # Metadata Footer
                    with ui.column().classes('p-2 w-full'):
                        ui.label(f"ID #{event['track_id']} | {event['label'].upper()}").classes('font-bold text-sm text-white')
                        
                        # Timestamp
                        # 'start_time' comes as string from sqlite query result in dict if using default row factory? 
                        # Wait, we manually zipped. SQLite TIMESTAMP usually returns string "YYYY-MM-DD HH:MM:SS".
                        ts_str = str(event['start_time']).split('.')[0]
                        ui.label(ts_str).classes('text-xs text-gray-400 font-mono')
                        
                        # Conf
                        conf_pct = int(event['max_conf'] * 100)
                        ui.badge(f"{conf_pct}% CONF", color='green' if conf_pct > 80 else 'yellow').classes('mt-1')

                    # On Click -> Open Fullscreen Dialog
                    # (Lambda needs default arg to capture 'event' in loop)
                    def open_details(e=event, wp=web_path):
                        with ui.dialog() as dialog, ui.card().classes('defense-card w-full max-w-4xl'):
                            ui.image(wp).classes('w-full rounded')
                            with ui.row().classes('w-full justify-between items-center mt-2'):
                                ui.label(f"TRACK ID: {e['track_id']} ({e['label']})").classes('text-xl font-mono font-bold')
                                ui.button('CLOSE', on_click=dialog.close).props('flat color=red')
                            
                            # JSON Data
                            import json
                            def json_serial(obj):
                                """JSON serializer for objects not serializable by default json code"""
                                if isinstance(obj, (datetime, date)):
                                    return obj.isoformat()
                                raise TypeError ("Type %s not serializable" % type(obj))

                            ui.code(json.dumps(e, indent=2, default=str), language='json').classes('w-full bg-black p-2 mt-2 text-xs')
                            
                        dialog.open()
                        
                    # Make whole card clickable? NiceGUI card isn't clickable by default.
                    # Wrap content in a button or use ui.link? 
                    # Easiest: Add a small "Inspect" button.
                    # Or use a trick: `on('click', ...)` on the card element.
                    # ui.card().on('click', ...) -> supported in recent NiceGUI.
                    
                    # Let's just add an icon button overlay
                    # ui.button(icon='zoom_in', on_click=open_details).props('flat round color=white').classes('absolute top-2 right-2 bg-black/50')
                    
                    # Better: Just click the image
                    # The image above is already inside.
                    # Let's make the label clickable for now to keep it simple or use a button at bottom.
                    ui.button('INSPECT', on_click=open_details).props('flat dense color=blue').classes('w-full')
