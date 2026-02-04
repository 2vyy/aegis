
import asyncio
import logging
import aiohttp
from aiohttp import web
import cv2
from aiortc import RTCPeerConnection, RTCSessionDescription
from camera_node.stream_manager import CameraStreamTrack
from camera_node.api import CameraConfigAPI

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("camera_node")

SERVER_URL = "http://localhost:8000/offer"
CAMERA_INDEX = 0

async def connect(pc, track):
    """Attempt to perform WebRTC signaling."""
    offer = await pc.createOffer()
    await pc.setLocalDescription(offer)
    
    payload = {
        "sdp": pc.localDescription.sdp,
        "type": pc.localDescription.type,
        "camera_id": CAMERA_INDEX
    }
    
    logger.info(f"Sending offer to {SERVER_URL}...")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(SERVER_URL, json=payload, timeout=2.0) as resp:
                if resp.status == 200:
                    answer_json = await resp.json()
                    logger.info("Received answer from server.")
                    answer = RTCSessionDescription(sdp=answer_json["sdp"], type=answer_json["type"])
                    await pc.setRemoteDescription(answer)
                    logger.info("WebRTC connection established!")
                    return True
                else:
                    logger.error(f"Failed to connect to server: {resp.status}")
    except Exception as e:
        logger.error(f"Signaling failed: {e}")
    return False

async def run():
    # 1. Create Peer Connection & Add Track
    pc = RTCPeerConnection()
    track = CameraStreamTrack(CAMERA_INDEX)
    pc.addTrack(track)

    # 2. Start Config API
    api = CameraConfigAPI(track)
    runner = web.AppRunner(api.app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8081)
    await site.start()
    logger.info("Camera Config API listening on 0.0.0.0:8081")

    logger.info("Press Ctrl+C to stop.")
    
    # DDIL State
    bg_sub = cv2.createBackgroundSubtractorKNN()
    
    try:
        while True:
            # Check connection state
            state = pc.connectionState
            
            if state in ("failed", "closed", "new"):
                logger.warning(f"Connection state is '{state}'. Entering Silent Watch (DDIL) mode.")
                
                # Try to reconnect
                logger.info("Attempting to reconnect...")
                success = await connect(pc, track)
                
                if not success:
                    # Still in DDIL mode - Silent Watch (Motion Detection)
                    # We manually read the camera since WebRTC isn't pulling frames
                    try:
                        if track.cap.isOpened():
                             ret, frame = track.cap.read()
                             if ret:
                                 # Resize for faster processing
                                 small_frame = cv2.resize(frame, (320, 240))
                                 fg_mask = bg_sub.apply(small_frame)
                                 # Threshold to binarize
                                 _, thresh = cv2.threshold(fg_mask, 200, 255, cv2.THRESH_BINARY)
                                 # Calculate motion ratio
                                 import numpy as np
                                 motion_ratio = np.count_nonzero(thresh) / (320 * 240)
                                 
                                 if motion_ratio > 0.05: # > 5% motion
                                     with open("pending.txt", "a") as f:
                                         import datetime
                                         ts = datetime.datetime.now().isoformat()
                                         # Log "Motion Detected"
                                         f.write(f"{ts} - [DDIL] CONFIRMED MOTION ({motion_ratio:.2f}) - buffered event\n")
                                         logger.warning(f"DDIL: Motion detected! ({motion_ratio:.2f})")
                    except Exception as e:
                        logger.error(f"DDIL error: {e}")
                    
                    # Wait before next retry
                    await asyncio.sleep(5)
                else:
                    # Reconnected!
                    logger.info("Reconnected to server.")
            else:
                # Connected (connecting or connected)
                await asyncio.sleep(1)
                
    except KeyboardInterrupt:
        pass
    finally:
        logger.info("Closing connection...")
        track.stop()
        await pc.close()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(run())
    except KeyboardInterrupt:
        pass
