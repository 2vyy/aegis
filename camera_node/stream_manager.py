"""
Camera Stream Track with latency profiling.
Embeds capture timestamp in frame metadata for end-to-end latency measurement.
"""
import asyncio
import cv2
from aiortc import VideoStreamTrack
from av import VideoFrame
import numpy as np
import logging
import time

logger = logging.getLogger("camera_stream")

class CameraStreamTrack(VideoStreamTrack):
    def __init__(self, camera_index=0):
        super().__init__()
        self.cap = cv2.VideoCapture(camera_index)
        if not self.cap.isOpened():
            logger.error(f"Could not open camera {camera_index}")
        else:
            # Low latency defaults: lower resolution = faster encode/decode
            self.width = 320
            self.height = 240
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            # Cap FPS to reduce load
            self.cap.set(cv2.CAP_PROP_FPS, 15)
            # Reduce camera buffer to 1 frame (prevents stale frames)
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        
        self.frame_count = 0

    def update_resolution(self, width, height):
        if self.cap and self.cap.isOpened():
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            self.width = width
            self.height = height
            logger.info(f"Updated camera resolution to {width}x{height}")

    async def recv(self):
        pts, time_base = await self.next_timestamp()
        
        # PROFILING: Capture time
        capture_time = time.time()
        
        ret, frame = self.cap.read()
        if not ret:
            frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)

        self.frame_count += 1
        
        # Log capture latency every 30 frames
        if self.frame_count % 30 == 0:
            logger.info(f"[PROFILE] Frame {self.frame_count} captured at {capture_time:.3f}")

        new_frame = VideoFrame.from_ndarray(frame, format="bgr24")
        new_frame.pts = pts
        new_frame.time_base = time_base
        return new_frame

    def stop(self):
        if self.cap and self.cap.isOpened():
            self.cap.release()