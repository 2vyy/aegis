"""
HLS Recorder
Pipes raw video frames to FFmpeg to generate an H.264 HLS stream.
Compatible with web playback via hls.js or native browser support.
"""
import os
import subprocess
import threading
import logging
import shutil
import numpy as np
import cv2

logger = logging.getLogger("recorder")

class HLSRecorder:
    def __init__(self, camera_id: str, width: int = 640, height: int = 480):
        self.camera_id = camera_id
        self.width = width
        self.height = height
        self.process = None
        self.recording = False
        self.stopping = False
        
        # Output directory: recordings/CAM_01/
        self.output_dir = os.path.join(os.getcwd(), "recordings", str(camera_id))
        os.makedirs(self.output_dir, exist_ok=True)
        
        # Cleanup old segments on init
        self._cleanup_stale_files()

    def _cleanup_stale_files(self):
        """Removes existing playlist/segments to start fresh."""
        if os.path.exists(self.output_dir):
            shutil.rmtree(self.output_dir)
            os.makedirs(self.output_dir, exist_ok=True)

    def start(self):
        """Starts the FFmpeg subprocess."""
        if self.recording:
            return

        output_playlist = os.path.join(self.output_dir, "stream.m3u8")
        
        # FFmpeg Command
        # 1. Input: Raw video pipe (pixel_format=bgr24)
        # 2. Encode: H.264 (libx264), ultrafast preset
        # 3. Output: HLS playlist, 10s segments, circular 24h buffer
        cmd = [
            "ffmpeg",
            "-y",                       # Overwrite output
            "-f", "rawvideo",           # Input format
            "-vcodec", "rawvideo",
            "-s", f"{self.width}x{self.height}",
            "-pix_fmt", "bgr24",        # OpenCV uses BGR
            "-r", "15",                 # Assumed framerate (match camera)
            "-i", "-",                  # Read from stdin
            
            "-c:v", "libx264",          # Encoder
            "-pix_fmt", "yuv420p",      # FORCE YUV420P for browser compatibility
            "-profile:v", "main",       # FORCE MAIN profile
            "-level", "3.0",
            "-preset", "veryfast",      # Low CPU usage
            "-tune", "zerolatency",
            "-g", "30",                 # GOP size (2s keyframe interval @ 15fps)
            "-sc_threshold", "0",       # Disable scene change detection for consistent GOP
            
            "-f", "hls",                # Format
            "-hls_time", "4",           # Target segment length
            "-hls_list_size", "20",     # Playlist size
            "-hls_flags", "delete_segments", 
            "-hls_segment_type", "fmp4", # Use Fragmented MP4
            "-start_number", "0",
            output_playlist
        ]
        
        try:
            # Capture stderr with a thread to avoid deadlock
            self.process = subprocess.Popen(
                cmd, 
                stdin=subprocess.PIPE, 
                stdout=subprocess.DEVNULL, 
                stderr=subprocess.PIPE 
            )
            self.recording = True
            
            # Start background thread to drain/log stderr
            self.stderr_thread = threading.Thread(target=self._monitor_stderr, daemon=True)
            self.stderr_thread.start()
            
            logger.info(f"Started HLS recording for {self.camera_id}")
            
        except Exception as e:
            logger.error(f"Failed to start FFmpeg: {e}")
            self.recording = False

    def _monitor_stderr(self):
        """Continuously reads FFmpeg stderr to log errors and prevent buffer deadlock."""
        if not self.process:
            return
            
        try:
            # Read line by line until process ends
            for line in iter(self.process.stderr.readline, b''):
                if line:
                    decoded = line.decode('utf-8', errors='ignore').strip()
                    # Filter out spammy info logs, keep warnings/errors
                    if "Error" in decoded or "Warning" in decoded or "fail" in decoded:
                        logger.warning(f"FFmpeg: {decoded}")
        except Exception as e:
            logger.error(f"Error monitoring FFmpeg stderr: {e}")
            
    def stop(self):
        self.stopping = True  # Prevent auto-restart
        self.recording = False
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
            self.process = None

    def _log_ffmpeg_error(self):
        # Deprecated by threaded monitor, but kept for interface compatibility
        pass

    def push_frame(self, frame: np.ndarray):
        """Writes a raw frame to the FFmpeg pipe."""
        if not self.recording or self.process is None:
            return

        try:
            # Verify dimensions (OpenCV gives h,w,c)
            h, w, _ = frame.shape
            if h != self.height or w != self.width:
                # Resize if mismatch (Crucial Fix)
                frame = cv2.resize(frame, (self.width, self.height))
                # logger.warning(f"Resized frame from {w}x{h} to {self.width}x{self.height}")

            # Write bytes
            self.process.stdin.write(frame.tobytes())
            self.process.stdin.flush()
        except (BrokenPipeError, ValueError):
            if not self.stopping:
                logger.error(f"FFmpeg pipe broken for {self.camera_id}. Restarting...")
                self._log_ffmpeg_error()
                self.stop()
                self.start()
        except Exception as e:
            if not self.stopping:
                logger.error(f"Error writing frame: {e}")
