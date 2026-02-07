"""
WebRTC video receiver with leaky bucket pattern.

Handles receiving video frames from camera nodes via WebRTC.
Uses a leaky bucket to prevent buffer bloat and minimize latency.
Integrates HLS Recording for 24/7 playback.
"""
import asyncio
import time
import threading
import logging
import numpy as np
from aiortc import RTCPeerConnection, RTCSessionDescription, MediaStreamTrack
from av import VideoFrame
from fastapi import FastAPI, Request

from server_node.core.frame_processor import FrameProcessor
from server_node.core.hls_recorder import HLSRecorder

logger = logging.getLogger("webrtc")

# Atomic frame buffer - frontends read from this
latest_frames = {}  # camera_id -> np.ndarray
frame_lock = threading.Lock()

# Track connected cameras
connected_cameras = set()

# WebRTC peer connections
pcs = set()

# FastAPI app for signaling
app = FastAPI()


# Track active receivers for cleanup
active_receivers = set()

class VideoReceiver:
    """
    Handles receiving and processing video frames from a WebRTC track.
    Uses LEAKY BUCKET pattern to prevent buffer bloat.
    """
    def __init__(self, track: MediaStreamTrack, camera_id: int):
        self.track = track
        self.camera_id = camera_id
        self.processor = FrameProcessor(camera_id)
        
        # HLS Recorder (320x240 matches config.py Camera defaults)
        self.recorder = HLSRecorder(str(camera_id), width=320, height=240)
        self.recorder.start()
        
        self.frame_count = 0
        self.running = True

    def stop(self):
        """Stops the receiver loop and recorder."""
        self.running = False
        self.recorder.stop()
        logger.info(f"Stopped receiver for camera {self.camera_id}")

    async def _drain_buffer(self) -> VideoFrame:
        """
        LEAKY BUCKET: Drain all pending frames, return only the newest.
        """
        frame = await self.track.recv()
        drained = 0
        
        while True:
            try:
                newer_frame = await asyncio.wait_for(self.track.recv(), timeout=0.001)
                frame = newer_frame
                drained += 1
            except asyncio.TimeoutError:
                break
        
        if drained > 0:
            logger.debug(f"[LEAKY BUCKET] Drained {drained} stale frames")
        
        return frame

    async def run(self):
        """
        Continuously receives frames from the track.
        Uses leaky bucket to always show the freshest frame.
        """
        throttle_rate = 1
        frame_count = 0
        
        try:
            while self.running:
                try:
                    recv_start = time.time()
                    # Add timeout to allow checking self.running periodically if stream hangs
                    frame = await asyncio.wait_for(self._drain_buffer(), timeout=1.0) 
                    recv_end = time.time()
                    
                    img = frame.to_ndarray(format="bgr24")
                    frame_count += 1

                    if frame_count % 30 == 0:
                        recv_latency = (recv_end - recv_start) * 1000
                        logger.info(f"[PROFILE] Frame {frame_count} drain took {recv_latency:.1f}ms")

                    # 1. HLS Recording (Push Clean Frame)
                    self.recorder.push_frame(img)

                    # 2. YOLO AI Processor
                    if frame_count % throttle_rate == 0:
                        output_frame = self.processor.process(img.copy())
                    else:
                        output_frame = img

                    # 3. Atomic Web UI Update
                    with frame_lock:
                        latest_frames[self.camera_id] = output_frame

                except asyncio.TimeoutError:
                    continue # Check self.running and retry
                except Exception as e:
                    logger.error("Track error for camera %s: %s", self.camera_id, e)
                    break
        finally:
            self.stop()
            connected_cameras.discard(self.camera_id)
            active_receivers.discard(self)


async def cleanup():
    """Global cleanup function to stop all receivers."""
    logger.info(f"Cleaning up {len(active_receivers)} active receivers...")
    for receiver in list(active_receivers):
        receiver.stop()
    # Close PeerConnections
    routines = [pc.close() for pc in pcs]
    await asyncio.gather(*routines)
    pcs.clear()

@app.post("/offer")
async def offer(request: Request):
    """
    WebRTC offer endpoint. Initiates a peer connection.
    """
    params = await request.json()
    camera_id = params.get("camera_id", 0)

    rtc_offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])

    pc = RTCPeerConnection()
    pcs.add(pc)

    @pc.on("track")
    def on_track(track):
        logger.info("Received track %s from camera %s", track.kind, camera_id)
        if track.kind == "video":
            connected_cameras.add(camera_id)
            receiver = VideoReceiver(track, camera_id)
            active_receivers.add(receiver)
            asyncio.ensure_future(receiver.run())

    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        if pc.connectionState in ("failed", "closed"):
            pcs.discard(pc)

    await pc.setRemoteDescription(rtc_offer)
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    return {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}
