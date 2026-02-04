
from aiohttp import web
import logging

logger = logging.getLogger("camera_api")

class CameraConfigAPI:
    def __init__(self, stream_track):
        self.stream_track = stream_track
        self.app = web.Application()
        self.app.add_routes([
            web.post('/config', self.update_config),
            web.get('/status', self.status)
        ])
        
    async def update_config(self, request):
        try:
            data = await request.json()
            logger.info(f"Received config update: {data}")
            
            # Apply config to stream track
            if "resolution" in data:
                width, height = map(int, data["resolution"].split("x"))
                self.stream_track.update_resolution(width, height)
                
            return web.json_response({"status": "ok", "config": data})
        except Exception as e:
            logger.error(f"Config update failed: {e}")
            return web.json_response({"status": "error", "message": str(e)}, status=500)

    async def status(self, request):
        return web.json_response({
            "alive": True,
            "resolution": f"{self.stream_track.width}x{self.stream_track.height}"
        })
