"""
WebRTC video receiver with leaky bucket pattern.

Handles receiving video frames from camera nodes via WebRTC.
Uses a leaky bucket to prevent buffer bloat and minimize latency.
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


class VideoReceiver:
    """
    Handles receiving and processing video frames from a WebRTC track.
    Uses LEAKY BUCKET pattern to prevent buffer bloat.
    """
    def __init__(self, track: MediaStreamTrack, camera_id: int):
        self.track = track
        self.camera_id = camera_id
        self.processor = FrameProcessor(camera_id)
        self.frame_count = 0

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
        
        while True:
            try:
                recv_start = time.time()
                frame = await self._drain_buffer()
                recv_end = time.time()
                
                img = frame.to_ndarray(format="bgr24")
                frame_count += 1

                if frame_count % 30 == 0:
                    recv_latency = (recv_end - recv_start) * 1000
                    logger.info(f"[PROFILE] Frame {frame_count} drain took {recv_latency:.1f}ms")

                # Always process frames through YOLO pipeline
                if frame_count % throttle_rate == 0:
                    output_frame = self.processor.process(img.copy())
                else:
                    output_frame = img

                # Atomic update
                with frame_lock:
                    latest_frames[self.camera_id] = output_frame

            except Exception as e:
                logger.error("Track ended or error for camera %s: %s", self.camera_id, e)
                connected_cameras.discard(self.camera_id)
                break


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
            asyncio.ensure_future(receiver.run())

    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        if pc.connectionState in ("failed", "closed"):
            pcs.discard(pc)

    await pc.setRemoteDescription(rtc_offer)
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    return {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}
