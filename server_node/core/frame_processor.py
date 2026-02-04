"""
Frame Processor: Server-side AI inference pipeline.

Pipeline:
1. YOLO Object Detection (Async, Threaded)
2. DeepSORT Tracking (Future Roadmap)
3. CoT Event Generation
"""
import cv2
import numpy as np
from concurrent.futures import ThreadPoolExecutor, Future
from ultralytics import YOLO
from server_node.core.cot import CoTGenerator


class FrameProcessor:
    """
    Processes video frames using YOLOv8 for object detection.
    Inference runs asynchronously in a background thread.
    """
    # Run YOLO every N frames to reduce GPU load
    INFERENCE_INTERVAL = 5

    def __init__(self, camera_id: int):
        self.camera_id = camera_id
        self.frame_count = 0
        
        # YOLO Inference State
        self.cached_boxes = []  # List of (coords, label, conf)
        self.inference_future: Future | None = None
        self.executor = ThreadPoolExecutor(max_workers=1)
        
        # Load YOLO model
        try:
            self.model = YOLO("yolov8n.pt")
            print("YOLOv8 model loaded successfully.")
        except Exception as e:
            print(f"Failed to load YOLO model: {e}")
            self.model = None

    def _run_inference(self, frame: np.ndarray):
        """Runs YOLO inference (called in background thread)."""
        if not self.model:
            return []
        
        results = self.model(frame, verbose=False)
        detections = []
        for result in results:
            for box in result.boxes:
                coords = box.xyxy[0].cpu().numpy().astype(int)
                conf = box.conf[0].item()
                cls = int(box.cls[0].item())
                label = self.model.names[cls]
                
                if conf > 0.5:
                    detections.append((coords, label, conf))
                    # Generate CoT event
                    cot_xml = CoTGenerator.generate_detection_event(label, conf)
                    print(f"[CoT EVENT]: {cot_xml}")
        return detections

    def process(self, frame: np.ndarray) -> np.ndarray:
        """
        Processes a single frame: runs YOLO asynchronously every N frames.
        Always draws the latest cached detection boxes on every frame.
        """
        self.frame_count += 1

        # --- Check for completed inference job ---
        if self.inference_future is not None and self.inference_future.done():
            try:
                self.cached_boxes = self.inference_future.result()
                
                # Update Asset Manager with detection count
                from server_node.core.asset_manager import asset_manager
                asset_manager.update_detections(self.camera_id, len(self.cached_boxes))
                
            except Exception as e:
                print(f"Inference error: {e}")
                self.cached_boxes = []
            self.inference_future = None
        
        # --- Submit new inference job every N frames ---
        if self.frame_count % self.INFERENCE_INTERVAL == 0 and self.model and self.inference_future is None:
            self.inference_future = self.executor.submit(self._run_inference, frame.copy())

        # --- Always draw cached boxes ---
        for coords, label, conf in self.cached_boxes:
            cv2.rectangle(frame, (coords[0], coords[1]), (coords[2], coords[3]), (0, 255, 0), 2)
            cv2.putText(frame, f"{label} {conf:.2f}", (coords[0], coords[1] - 10), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

        return frame
